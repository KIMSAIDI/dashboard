import requests
import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import plotly.express as px
import warnings
import plotly.graph_objects as go


warnings.filterwarnings("ignore", message=".*NotOpenSSLWarning.*")

from score import extract_scores
scores_max = extract_scores("Levels")
scores_max["Infiltration"]["mission08"] = 3976 # pas de valeur dans le .xml donc obligé de le faire à la main


def fetch_lrs_data(identifier):
    endpoint = "https://lrsels.lip6.fr/data/xAPI/statements"
    headers = {"X-Experience-API-Version": "1.0.3"}
    auth = ("9fe9fa9a494f2b34b3cf355dcf20219d7be35b14", "b547a66817be9c2dbad2a5f583e704397c9db809")
    params = {"agent": f'{{"account": {{"homePage": "https://www.lip6.fr/mocah/", "name": "{identifier}"}}}}', "limit": 500}
    response = requests.get(endpoint, headers=headers, auth=auth, params=params)
    if response.status_code == 200:
        return response.json()["statements"]
    else:
        raise Exception(f"Error fetching data: {response.status_code}, {response.text}")

def process_data(data):
    records = []
    last_mission_level = None
    all_mission_levels = set()
    completed_counts = {}
    score_by_level = {}

    for statement in data:
        try:
            success = statement.get("result", {}).get("success", False)
            score = statement.get("result", {}).get("extensions", {}).get("https://spy.lip6.fr/xapi/extensions/score", None)

            if not success:
                score = 0

            if score:
                if isinstance(score, list) and len(score) > 0:
                    score = score[0]

                if isinstance(score, str):
                    score = float(score)

                if isinstance(score, (int, float)):
                    score = float(score)
                else:
                    score = None
            else:
                score = None

            mission_level = None
            scenario = None
            if "object" in statement:
                object_data = statement["object"]
                if "definition" in object_data:
                    definition = object_data["definition"]
                    if "extensions" in definition:
                        extensions = definition["extensions"]
                        if "https://w3id.org/xapi/seriousgames/extensions/progress" in extensions:
                            mission_level = extensions["https://w3id.org/xapi/seriousgames/extensions/progress"][0]
                        if "https://spy.lip6.fr/xapi/extensions/context" in extensions:
                            scenario = extensions["https://spy.lip6.fr/xapi/extensions/context"][0]

            if mission_level is None and last_mission_level is not None:
                mission_level = last_mission_level

            if mission_level is not None:
                last_mission_level = mission_level
                all_mission_levels.add(mission_level)

                verb = statement["verb"]["id"].split("/")[-1]
                if verb == "completed":
                    if mission_level not in completed_counts:
                        completed_counts[mission_level] = 0
                    completed_counts[mission_level] += 1

                if mission_level not in score_by_level:
                    score_by_level[mission_level] = []
                if score is not None:
                    score_by_level[mission_level].append(score)

            records.append({
                "Timestamp": statement.get("timestamp"),
                "Verb": statement["verb"]["id"].split("/")[-1],
                "Actor": statement["actor"].get("name", "Unknown"),
                "Object": statement["object"].get("id", "Unknown"),
                "Score": score,
                "Mission Level": mission_level,
                "Scenario": scenario
            })
        except Exception as e:
            continue

        avg_score_by_level = {
            level: round(sum(scores) / len(scores)) if len(scores) > 0 else None
            for level, scores in score_by_level.items()
        }


    df = pd.DataFrame(records)
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    return df, list(all_mission_levels), completed_counts, avg_score_by_level, score_by_level

def calculate_time_per_level(df):
    if df["Mission Level"].isnull().all():
        print("Aucun niveau détecté dans les données.")
        return pd.DataFrame(columns=["Mission Level", "Time Spent (min)"])

    # Trier par niveau et timestamp
    df = df.sort_values(by=["Mission Level", "Timestamp"])

    # Calculer les durées par sessions
    session_times = []
    for level, group in df.groupby("Mission Level"):
        group = group.reset_index(drop=True)
        time_diffs = group["Timestamp"].diff().dt.total_seconds() / 60  # Différences en minutes
        time_diffs = time_diffs.fillna(0)  # Remplir les NaN pour la première ligne
        total_time = time_diffs[time_diffs <= 60].sum()  # Ignorer les écarts > 60 minutes
        session_times.append({"Mission Level": level, "Time Spent (min)": round(total_time, 2)})

    time_spent = pd.DataFrame(session_times)

    # Filtrer les anomalies (exemple : sessions > 24 heures)
    threshold = 24 * 60
    anomalies = time_spent[time_spent["Time Spent (min)"] > threshold]
    if not anomalies.empty:
        print("Anomalies détectées :")
        print(anomalies)
        time_spent = time_spent[time_spent["Time Spent (min)"] <= threshold]

    return time_spent



def prepare_score_data(avg_score_by_level, all_levels):
    scores_with_zeros = {level: avg_score_by_level.get(level, 0) for level in all_levels}
    sorted_scores = dict(sorted(scores_with_zeros.items(), key=lambda item: item[0]))
    return sorted_scores


app = dash.Dash(__name__, suppress_callback_exceptions=True)
app.title = "Tableau de bord avec vue alternée"

app.layout = html.Div(id="app-container", children=[
    dcc.Location(id='url', refresh=False),

    # Login Page
    html.Div([
        html.Label("Bienvenue sur ton tableau de bord !", className="login-title"),
        dcc.Input(id='input-identifier', type='text', placeholder='Entre ton code SPY (ex : A64881E9)', className="login-input"),
        html.Button("Accéder à ta progression", id='login-button', n_clicks=0, className="login-button"),
        html.Div(id='login-error', style={'color': 'red'}),
    ], id='login-page', style={'display': 'block', 'textAlign': 'center'}),

    # Dashboard Page
    html.Div([
        html.Div([
            html.Button("Déconnexion", id='logout-button', n_clicks=0, className="logout-button"),
            html.Button("Basculer la vue", id='toggle-view-button', n_clicks=0, className="toggle-view-button"),
            html.H1("Tableau de bord", className='dashboard-title'),
        ]),
        html.Div(id='graphs-view', style={'display': 'block'}),
        html.Div([
            html.H2("Analyse ta progression sur chaque niveau.", className='dashboard-mission-title'),
            dcc.Dropdown(
                id='mission-filter',
                placeholder="Filtrer par mission",
                options=[],
                multi=False,
            ),
            html.Div(id='table-view-content')
        ], id='table-view', style={'display': 'none'}),
    ], id='dashboard-page', style={'display': 'none'}),


html.Label("© SU | ISG 2025 - Projet réalisé par Aans TAHIR, Kim SAIDI, Maéva DORMANT & Saad MOUSSTAID.", className='footer'),

])


@app.callback(
    [
        Output('login-page', 'style'),
        Output('dashboard-page', 'style'),
        Output('login-error', 'children'),
        Output('graphs-view', 'children'),
        Output('mission-filter', 'options')
    ],
    [Input('login-button', 'n_clicks'), Input('logout-button', 'n_clicks')],
    [State('input-identifier', 'value')]
)
def manage_login(n_login, n_logout, identifier):
    ctx = dash.callback_context
    if not ctx.triggered:
        return {'display': 'block'}, {'display': 'none'}, '', '', []

    if ctx.triggered[0]['prop_id'].startswith('login-button'):
        if identifier and identifier.strip():
            try:
                data = fetch_lrs_data(identifier)
                df, mission_levels, completed_counts, avg_score_by_level, score_by_level = process_data(data)

                # #remise à niveau de tout les scores
                for mission, score in avg_score_by_level.items():
                    for niveau, score_max in scores_max["Infiltration"].items():
                        if mission == niveau:
                           
                            if score == None:
                                avg_score_by_level[mission] = 0
                            elif score > score_max:
                                avg_score_by_level[mission] = 100
                            else :
                                avg_score_by_level[mission] = round((score / score_max) * 100, 1) 
                            
                
                time_spent = calculate_time_per_level(df)
                time_spent_dict = time_spent.set_index("Mission Level")["Time Spent (min)"].to_dict()
                df["Time Spent (min)"] = df["Mission Level"].map(time_spent_dict)

                df["Nombre d'essai"] = df["Mission Level"].map(lambda x: len(score_by_level.get(x, [])))

                sorted_scores = prepare_score_data({level: (score if score is not None else 0) for level, score in avg_score_by_level.items()}, mission_levels)

                mission_levels = sorted(mission_levels)

                
                # Graphique pour l'évolution des scores
                sorted_scores_df = pd.DataFrame({
                    "Mission Level": list(sorted_scores.keys()),
                    "Average Score": [round(value, 2) for value in sorted_scores.values()]
                }).sort_values(by="Mission Level")

                fig_score_evolution = px.line(
                    sorted_scores_df,
                    x="Mission Level",
                    y="Average Score",
                    title="Évolution des scores par niveau de mission",
                    labels={"Mission Level": "Niveau de Mission", "Average Score": "Score Moyen (%)"},
                    markers=True,
                    template="seaborn"
                )
                fig_score_evolution.update_layout(yaxis_tickformat=".1f%%", yaxis=dict(range=[0, 105]))

                # Graphique pour le nombre d'essais
                attempts_data = pd.DataFrame({
                    "Mission Level": list(score_by_level.keys()),
                    "Nombre d'essai": [len(scores) for scores in score_by_level.values()]
                }).sort_values(by="Mission Level")
                fig_attempts = px.bar(
                    attempts_data,
                    x="Nombre d'essai",
                    y="Mission Level",
                    orientation='h',
                    title="Nombre d'essais par niveau",
                    labels={"Mission Level": "Niveau de Mission", "Nombre d'essai": "Nombre d'Essais"},
                    color="Nombre d'essai",
                    color_continuous_scale="Burg"
                    
                )


                # Graphique pour le temps passé
                
                # Trier les données du temps passé par niveau de mission
                # Trier les missions par ordre de mission
                time_spent_sorted = time_spent.sort_values(by="Mission Level")  # Tri par Mission Level (ordre croissant)

                # Créer un graphique en barres horizontales
                fig_time_spent = px.bar(
                    time_spent_sorted,
                    x="Time Spent (min)",
                    y="Mission Level",
                    orientation='h',
                    title="Temps passé par niveau",
                    labels={"Mission Level": "Niveau de Mission", "Time Spent (min)": "Temps Passé (min)"},
                    color="Time Spent (min)",
                    color_continuous_scale="Blugrn"  # Palette de couleurs avec des tons plus contrastés
                )

                # Ajuster le layout pour s'assurer que les missions sont bien triées
                fig_time_spent.update_layout(
                    yaxis=dict(categoryorder="array", categoryarray=time_spent_sorted["Mission Level"]),
                    template="seaborn"  # Thème clair pour une meilleure lisibilité
                )




                # Intégrer les graphiques
                graphs = html.Div([
                    html.Div([
                        html.Div("Évolution des scores par niveau de mission", className="graph-title"),
                        dcc.Graph(id='score-evolution', figure=fig_score_evolution)
                    ], className="graph-container"),

                    html.Div([
                        html.Div("Nombre d'essais par niveau", className="graph-title"),
                        dcc.Graph(id='attempts-graph', figure=fig_attempts)
                    ], className="graph-container"),

                    html.Div([
                        html.Div("Temps passé par niveau", className="graph-title"),
                        dcc.Graph(id='time-spent-graph', figure=fig_time_spent)
                    ], className="graph-container"),
                ])


                # pour trier les niveaux
               
                options = [{'label': level, 'value': level} for level in mission_levels]

                return {'display': 'none'}, {'display': 'block'}, '', graphs, options
            except Exception as e:
                return {'display': 'block'}, {'display': 'none'}, "Identifiant invalide.", '', []
        else:
            return {'display': 'block'}, {'display': 'none'}, "Veuillez entrer un identifiant.", '', []

    if ctx.triggered[0]['prop_id'].startswith('logout-button'):
        return {'display': 'block'}, {'display': 'none'}, '', '', []

    return {'display': 'block'}, {'display': 'none'}, '', '', []



def generate_feedback(score, max_score):
    if score is None or max_score is None or max_score == 0:
        return "☆ ☆ ☆"  # Pas de score ou score invalide
    percentage = (score / max_score) * 100
    if percentage >= 90:
        return "★ ★ ★"
    elif percentage >= 70:
        return "★ ★ ☆"
    else:
        return "★ ☆ ☆"



def get_penguin_feedback(score, max_score):
    if score is None or max_score is None or max_score == 0:
        return {
            "comment": "Ne vous découragez pas, vous y arriverez ! 🐧",
            "image": "/assets/penguin_sad.png"
        }
    percentage = (score / max_score) * 100
    if percentage >= 90:
        return {
            "comment": "Excellent travail ! Vous êtes un expert ! 🐧",
            "image": "/assets/penguin_happy.png"
        }
    elif percentage >= 70:
        return {
            "comment": "Bon travail, mais vous pouvez encore progresser ! 🐧",
            "image": "/assets/penguin_neutral.png"
        }
    else:
        return {
            "comment": "Ne vous découragez pas, vous y arriverez ! 🐧",
            "image": "/assets/penguin_sad.png"
        }



@app.callback(
    Output('table-view-content', 'children'),
    [Input('mission-filter', 'value')],
    [State('input-identifier', 'value')]
)
def filter_table(selected_mission, identifier):
    if not identifier:
        return html.Div(["Aucune donnée disponible."], style={'display': 'block', 'color': 'white'})
    try:
        data = fetch_lrs_data(identifier)
        df, _, _, _, score_by_level = process_data(data)
        print("selected_mission :", selected_mission)

        # Filtrer pour ne garder que les lignes avec un score non nul
        df = df[df['Score'].notna() & (df['Score'] != 0)]

        # Arrondir tous les scores à 2 décimales
        df["Score"] = df["Score"].apply(lambda x: round(x, 2) if pd.notnull(x) else x)

        # Ajouter une colonne "Essai" pour le comptage des essais
        df['Essai'] = df.groupby('Mission Level').cumcount() + 1

        if selected_mission:
            df = df[df["Mission Level"] == selected_mission]

        # Ajouter la colonne Feedback
        df["Feedback"] = df.apply(
            lambda row: generate_feedback(row["Score"], scores_max["Infiltration"].get(row["Mission Level"], None)),
            axis=1
        )

        # Tableau pour afficher le Score, le Nombre d'Essai, et le Feedback
        score_table = dash_table.DataTable(
            id='score-table',
            columns=[
                {"name": "Essai", "id": "Essai"},
                {"name": "Score", "id": "Score"},
                {"name": "Feedback", "id": "Feedback"}
            ],
            data=df.to_dict('records'),
            style_table={'height': '100%', 'overflowY': 'auto', 'margin': '10px', 'align-items': 'center'},
            style_cell={'textAlign': 'center', 'font-size': '16px'}
        )

        # Calcul des statistiques (Score moyen, le plus haut, et le plus bas)
        if selected_mission:
            mission_scores = df[df["Mission Level"] == selected_mission]["Score"]
        else:
            mission_scores = df["Score"]

        stats_data = {
            "Score le plus haut": (
                round(mission_scores.max(), 2) if not mission_scores.empty else None
            ),
            "Score Moyen": (
                round(mission_scores.mean(), 2) if not mission_scores.empty else None
            ),
            "Score le plus bas obtenu": (
                round(mission_scores.min(), 2) if not mission_scores.empty else None
            )
        }

        # Tableau pour les statistiques
        stats_table = dash_table.DataTable(
            id='stats-table',
            columns=[
                {"name": "Score le plus haut", "id": "Score le plus haut"},
                {"name": "Score Moyen", "id": "Score Moyen"},
                {"name": "Score le plus bas obtenu", "id": "Score le plus bas obtenu"}
            ],
            data=[stats_data],
            style_table={'height': '100%', 'overflowY': 'auto', 'margin': '10px', 'align-items': 'center'},
            style_cell={'textAlign': 'center', 'font-size': '16px'},
            style_data_conditional=[
                {
                    'if': {'column_id': 'Score le plus haut'},
                    'backgroundColor': '#28a745',  # Fond vert
                    'color': 'white'  # Texte blanc
                },
                {
                    'if': {'column_id': 'Score le plus bas obtenu'},
                    'backgroundColor': 'red',  # Fond rouge
                    'color': 'white'  # Texte blanc
                }
            ]
        )


        # Générer le feedback du penguin
        if not df.empty:
            recent_score = df["Score"].iloc[-1]  # Dernier score enregistré
            max_score = scores_max["Infiltration"].get(df["Mission Level"].iloc[-1], None)
            penguin_feedback_data = get_penguin_feedback(recent_score, max_score)
        else:
            penguin_feedback_data = {
                "comment": "Aucun score disponible pour l'instant. Essayez une mission ! 🐧",
                "image": "/assets/penguin_idle.png"
            }

        # Composant pour le penguin
        penguin_feedback = html.Div([
            html.Img(
                src=penguin_feedback_data["image"],
                style={
                    "width": "200px",
                    "float": "left",
                    "margin": "20px"
                }
            ),
            html.Div(
                penguin_feedback_data["comment"],
                style={
                    "text-align": "center",
                    "font-size": "18px",
                    "font-weight": "bold",
                    "color": "#ffffff",
                    "background-color": "#005656",
                    "padding": "10px",
                    "border-radius": "10px",
                    "margin-top": "10px",
                    "width": "fit-content",
                    "margin-left": "auto",
                    "margin-right": "auto"
                }
            )
        ])

        # Retourner les tableaux et le feedback du penguin
        return html.Div([
            html.Div(stats_table, className="table-container"),
            html.Div(score_table, className="table-container"),
            penguin_feedback
        ])

    except Exception as e:
        print(f"Erreur lors de la récupération des données : {e}")
        return html.Div("Erreur lors de la récupération des données.")

    
@app.callback(
    [Output('graphs-view', 'style'), Output('table-view', 'style')],
    [Input('toggle-view-button', 'n_clicks')]
)
def toggle_view(n_clicks):
    if n_clicks % 2 == 0:
        return {'display': 'block'}, {'display': 'none'}
    else:
        return {'display': 'none'}, {'display': 'block'}


if __name__ == '__main__':
    app.run_server(debug=True)
import requests
import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import plotly.express as px
import warnings

warnings.filterwarnings("ignore", message=".*NotOpenSSLWarning.*")

from score import extract_scores
scores_max = extract_scores("Levels")
scores_max["Infiltration"]["mission08"] = 3976 # à remplacer par la vrai valeur


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
       # print("avg_score_by_level :", avg_score_by_level)
       #² print("scores_max['Infiltration'] :", scores_max["Infiltration"])

        # # Remise à niveau des scores pour les transformer en pourcentages
        # for mission, score in avg_score_by_level.items():
        #     for niveau, score_max in scores_max["Infiltration"].items():
        #         if mission == niveau and score_max > 0:
        #             avg_score_by_level[mission] = round((score / score_max) * 100, 1)


    df = pd.DataFrame(records)
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    return df, list(all_mission_levels), completed_counts, avg_score_by_level, score_by_level

def calculate_time_per_level(df):
    if df["Mission Level"].isnull().all():
        print("Aucun niveau détecté dans les données.")
        return pd.DataFrame(columns=["Mission Level", "Time Spent (min)"])

    time_spent = (
        df.dropna(subset=["Mission Level"])
        .groupby("Mission Level")["Timestamp"]
        .agg(lambda x: (x.max() - x.min()).total_seconds() / 60)
        .reset_index(name="Time Spent (min)")
    )

    threshold = 24 * 60
    anomalies = time_spent[time_spent["Time Spent (min)"] > threshold]
    if not anomalies.empty:
        print("Anomalies détectées :")
        print(anomalies)
        time_spent = time_spent[time_spent["Time Spent (min)"] <= threshold]

    #print("Contenu final de time_spent :")
    #print(time_spent)

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

                fig_score_evolution = px.line(
                    pd.DataFrame({"Mission Level": list(sorted_scores.keys()), "Average Score": list(sorted_scores.values())}),
                    x="Mission Level", 
                    y="Average Score",
                    title="Évolution des scores par niveau de mission",
                    labels={"Mission Level": "Niveau de Mission", "Average Score": "Score Moyen (%)"},
                    markers=True  # Ajout de marqueurs pour une meilleure lisibilité
                )

                # Mise en forme de l'axe Y et ajout des limites (0 à 100)
                fig_score_evolution.update_layout(
                    yaxis_tickformat=".1f%%",  # Affiche les valeurs en pourcentage
                    yaxis=dict(range=[0, 105]),  # Limite l'axe Y entre 0 et 105
                    title={
                        'text': "Évolution des scores par niveau de mission",
                        'x': 0.5,
                        'xanchor': 'center'
                    }
                )



                fig_attempts = px.bar(
                    pd.DataFrame({"Mission Level": list(score_by_level.keys()), "Nombre d'essai": [len(scores) for scores in score_by_level.values()]}),
                    x="Mission Level", y="Nombre d'essai",
                    title="Nombre d'essais par niveau de mission",
                    labels={"Mission Level": "Niveau de Mission", "Nombre d'essai": "Nombre d'Essais"}
                )

                fig_time_spent = px.bar(
                    time_spent,
                    x="Mission Level", y="Time Spent (min)",
                    title="Temps passé par niveau",
                    labels={"Mission Level": "Niveau de Mission", "Time Spent (min)": "Temps Passé (min)"}
                )

                graphs = html.Div([
                    dcc.Graph(id='score-evolution', figure=fig_score_evolution),
                    dcc.Graph(id='time-spent-graph', figure=fig_time_spent),
                    dcc.Graph(id='attempts-graph', figure=fig_attempts)
                ])

                options = [{'label': level, 'value': level} for level in mission_levels]

                return {'display': 'none'}, {'display': 'block'}, '', graphs, options
            except Exception as e:
                return {'display': 'block'}, {'display': 'none'}, "Identifiant invalide.", '', []
        else:
            return {'display': 'block'}, {'display': 'none'}, "Veuillez entrer un identifiant.", '', []

    if ctx.triggered[0]['prop_id'].startswith('logout-button'):
        return {'display': 'block'}, {'display': 'none'}, '', '', []

    return {'display': 'block'}, {'display': 'none'}, '', '', []


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

        # Filtrer pour ne garder que les lignes avec un score non nul
        df = df[df['Score'].notna() & (df['Score'] != 0)]

        # Ajouter une colonne "Essai" pour le comptage des essais
        df['Essai'] = df.groupby('Mission Level').cumcount() + 1

        if selected_mission:
            df = df[df["Mission Level"] == selected_mission]

        # Tableau pour afficher le Score et le Nombre d'Essai
        score_table = dash_table.DataTable(
            id='score-table',
            columns=[
                {"name": "Essai", "id": "Essai"},
                {"name": "Score", "id": "Score"},
                {"name": "Feedback", "id": "Feedback"}
            ],
            data=df.to_dict('records'),
            style_table={'height': '100%', 'overflowY': 'auto', 'margin': '10px', 'align-items': 'center'},
            style_cell={'textAlign': 'center'}
        )

        # Calcul des statistiques (Score moyen, plus haut et plus bas)
        if selected_mission:
            mission_scores = df[df["Mission Level"] == selected_mission]["Score"]
        else:
            mission_scores = df["Score"]
        
        if selected_mission in scores_max["Infiltration"]:
            print(f"selected_mission: {selected_mission}, "
                f"score_max: {scores_max['Infiltration'][selected_mission]}, "
                f"mission_scores.max(): {mission_scores.max()}")
        if mission_scores.min() is not None:
            print(f"mission_scores.min(): {mission_scores.min()}")

        stats_data = {
            "Score le plus haut": (
                scores_max["Infiltration"][selected_mission]
                if selected_mission in scores_max["Infiltration"]
                and mission_scores.max() is not None
                and scores_max["Infiltration"][selected_mission] >= mission_scores.max()
                else mission_scores.max()
                if mission_scores.max() is not None
                else None
            ),
            "Score Moyen": round(mission_scores.mean()) if not mission_scores.empty else None,
            "Score le plus bas obtenu": (
                mission_scores.min()
                if mission_scores.min() is not None
                else None
            )
        }


        stats_table = dash_table.DataTable(
            id='stats-table',
            columns=[
                {"name": "Score le plus haut", "id": "Score le plus haut"},
                {"name": "Score Moyen", "id": "Score Moyen"},
                {"name": "Score le plus bas", "id": "Score le plus bas"},
            ],
            style_data_conditional=[
                {
                    'if': {'column_id': 'Score le plus haut'},
                    'backgroundColor': '#28a745',  # Couleur verte
                    'color': 'white',  # Couleur du texte
                },
                {
                    'if': {'column_id': 'Score le plus bas'},
                    'backgroundColor': 'red',  # Couleur verte
                    'color': 'white',  # Couleur du texte
                }
            ],
            data=[{
                "Score le plus haut": stats_data["Score le plus haut"],
                "Score Moyen": stats_data["Score Moyen"],
                "Score le plus bas": stats_data["Score le plus bas"]
            }],
            style_table={'height': '100%', 'overflowY': 'auto', 'margin': '10px', 'align-items': 'center'},
            style_cell={'textAlign': 'center'}
        )

        return html.Div([
            stats_table,
            score_table
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
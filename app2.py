import requests
import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import plotly.express as px
import warnings

warnings.filterwarnings("ignore", message=".*NotOpenSSLWarning.*")

def fetch_lrs_data():
    endpoint = "https://lrsels.lip6.fr/data/xAPI/statements"
    headers = {"X-Experience-API-Version": "1.0.3"}
    auth = ("9fe9fa9a494f2b34b3cf355dcf20219d7be35b14", "b547a66817be9c2dbad2a5f583e704397c9db809")
    params = {"agent": '{"account": {"homePage": "https://www.lip6.fr/mocah/", "name": "C2ED0A43"}}', "limit": 500}
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
                score = None

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
    return df, list(all_mission_levels), completed_counts, avg_score_by_level

def calculate_time_per_level(df):
    if df["Mission Level"].isnull().all():
        print("Aucun niveau détecté dans les données.")
        return pd.DataFrame(columns=["Mission Level", "Time Spent (min)"])

    time_spent = (
        df.dropna(subset=["Mission Level"])  # Supprime les lignes sans niveau
        .groupby("Mission Level")["Timestamp"]
        .agg(lambda x: (x.max() - x.min()).total_seconds() / 60)  # Convertit en minutes
        .reset_index(name="Time Spent (min)")
    )

    # Filtrer les durées anormalement longues (> 24h par exemple)
    threshold = 24 * 60  # 24 heures en minutes
    anomalies = time_spent[time_spent["Time Spent (min)"] > threshold]
    if not anomalies.empty:
        print("Anomalies détectées :")
        print(anomalies)
        time_spent = time_spent[time_spent["Time Spent (min)"] <= threshold]

    print("Contenu final de time_spent :")
    print(time_spent)

    return time_spent

def prepare_score_data(avg_score_by_level):
    # Filtrer les niveaux sans score
    filtered_scores = {level: score for level, score in avg_score_by_level.items() if score is not None}
    # Trier les scores par niveau
    sorted_scores = dict(sorted(filtered_scores.items(), key=lambda item: item[0]))
    return sorted_scores

# Initial data
data = fetch_lrs_data()
actor_name = "Joueur"  # Replace with dynamic actor name if available
df, mission_levels, completed_counts, avg_score_by_level = process_data(data)
time_spent = calculate_time_per_level(df)

# Merge time spent into the main DataFrame
time_spent_dict = time_spent.set_index("Mission Level")["Time Spent (min)"].to_dict()
df["Time Spent (min)"] = df["Mission Level"].map(time_spent_dict)

# Préparer les données des scores
sorted_scores = prepare_score_data(avg_score_by_level)
fig_score_evolution = px.line(
    pd.DataFrame({"Mission Level": list(sorted_scores.keys()), "Average Score": list(sorted_scores.values())}),
    x="Mission Level", y="Average Score",
    title="Évolution des scores par niveau de mission",
    labels={"Mission Level": "Niveau de Mission", "Average Score": "Score Moyen"}
)

app = dash.Dash(__name__)

app.layout = html.Div([
    html.Div([
        html.Button(f"Joueur n°{actor_name}", id="toggle-id-button", n_clicks=0, className="toggle-id-button"),
        html.Button("Basculer la vue", id="toggle-view-button", n_clicks=0, className="toggle-view-button"),
    ], className='header-container'),

    html.Div([
        html.H1("Suivre ma progression", className='dashboard-title'),
        html.Div(id='view-container', children=[
            # Graphs view
            html.Div([
                html.Div([
                    dcc.Graph(
                        id='score-evolution',
                        figure=fig_score_evolution
                    )
                ], className="dash-graph-container"),

                html.Div([
                    dcc.Graph(
                        id='time-spent-graph',
                        figure=px.bar(
                            time_spent,
                            x="Mission Level", y="Time Spent (min)",
                            title="Temps passé par niveau",
                            labels={"Mission Level": "Niveau de Mission", "Time Spent (min)": "Temps Passé (min)"}
                        )
                    )
                ], className="dash-graph-container"),
            ], id="graphs-view", style={'display': 'block'}),

            # Table view
            html.Div([
                html.Div([
                    dash_table.DataTable(
                        id='progress-table',
                        columns=[
                            {"name": "Mission Level", "id": "Mission Level"},
                            {"name": "Time Spent (min)", "id": "Time Spent (min)"},
                            {"name": "Score", "id": "Score"},
                            {"name": "Verb", "id": "Verb"},
                            {"name": "Actor", "id": "Actor"}
                        ],
                        data=df.to_dict('records'),
                        style_table={'height': '400px', 'overflowY': 'auto'},
                        style_cell={'textAlign': 'center', 'padding': '10px'}
                    )
                ], className="dash-table-box"),
            ], id="table-view", style={'display': 'none'}),
        ])
    ], className='dashboard-container'),
], className='dashboard')

@app.callback(
    [Output('graphs-view', 'style'),
     Output('table-view', 'style')],
    [Input('toggle-view-button', 'n_clicks')]
)
def toggle_view(n_clicks):
    if n_clicks % 2 == 0:
        return {'display': 'block'}, {'display': 'none'}
    else:
        return {'display': 'none'}, {'display': 'block'}

if __name__ == '__main__':
    app.run_server(debug=True)

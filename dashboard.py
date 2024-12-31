import requests
import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output
import plotly.express as px

# Function to fetch data from LRS
def fetch_lrs_data():
    endpoint = "https://lrsels.lip6.fr/data/xAPI/statements"
    headers = {
        "X-Experience-API-Version": "1.0.3"
    }
    auth = ("9fe9fa9a494f2b34b3cf355dcf20219d7be35b14", "b547a66817be9c2dbad2a5f583e704397c9db809")

    params = {
        "agent": '{"account": {"homePage": "https://www.lip6.fr/mocah/", "name": "C2ED0A43"}}',
        "limit": 500
    }

    response = requests.get(endpoint, headers=headers, auth=auth, params=params)

    if response.status_code == 200:
        data = response.json()["statements"]
        return data
    else:
        raise Exception(f"Error fetching data: {response.status_code}, {response.text}")

def process_data(data):
    records = []
    last_mission_level = None

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
            if "object" in statement:
                object_data = statement["object"]
                if "definition" in object_data:
                    definition = object_data["definition"]
                    if "extensions" in definition:
                        extensions = definition["extensions"]
                        if "https://w3id.org/xapi/seriousgames/extensions/progress" in extensions:
                            mission_level = extensions["https://w3id.org/xapi/seriousgames/extensions/progress"][0]

            if mission_level is None and last_mission_level is not None:
                mission_level = last_mission_level

            if mission_level is not None:
                last_mission_level = mission_level

            records.append({
                "Timestamp": statement.get("timestamp"),
                "Verb": statement["verb"]["id"].split("/")[-1],
                "Actor": statement["actor"].get("name", "Unknown"),
                "Object": statement["object"].get("id", "Unknown"),
                "Score": score,
                "Mission Level": mission_level
            })
        except Exception as e:
            continue

    # Create DataFrame and sort by Timestamp
    df = pd.DataFrame(records)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    df = df.sort_values(by="Timestamp")

    # Remove duplicates based on 'Score', 'Mission Level', and 'Timestamp'
    df = df.drop_duplicates(subset=["Score", "Mission Level", "Timestamp"], keep="first")

    
    return df


# Create Dash app
app = dash.Dash(__name__)

# Initial data
data = fetch_lrs_data()
df = process_data(data)

app.layout = html.Div([
    html.H1("LRS Dashboard", style={'textAlign': 'center', 'marginBottom': '30px'}),

    html.Div([
        html.Div([
            html.Label("Filtrer par Verb:"),
            dcc.Dropdown(
                id='verb-filter',
                options=[{"label": verb, "value": verb} for verb in df["Verb"].unique()],
                multi=True,
                placeholder="Sélectionnez un ou plusieurs verbes",
                style={'width': '100%', 'marginBottom': '20px'}
            ),

            html.Label("Afficher uniquement les lignes avec score:"),
            dcc.Checklist(
                id='score-filter',
                options=[{'label': 'Avec score', 'value': 'with_score'}],
                value=[],
                inline=True,
                style={'marginBottom': '20px'}
            ),

            html.Label("Filtrer par Mission Level:"),
            dcc.Dropdown(
                id='mission-filter',
                options=[{"label": level, "value": level} for level in df["Mission Level"].unique() if level is not None],
                multi=True,
                placeholder="Sélectionnez un ou plusieurs niveaux de mission",
                style={'width': '100%', 'marginBottom': '20px'}
            ),

            html.Button("Rafraîchir", id='refresh-button', n_clicks=0, style={'marginBottom': '20px', 'width': '100%'}),
        ], className='sidebar', style={'width': '25%', 'float': 'left', 'padding': '20px'}),

        html.Div([
            html.Label("Évolution des scores par niveau de mission :"),
            dcc.Graph(id='score-evolution', style={'marginBottom': '30px'}),

            dash_table.DataTable(
                id='table',
                columns=[
                    {"name": "Timestamp", "id": "Timestamp"},
                    {"name": "Verb", "id": "Verb"},
                    {"name": "Actor", "id": "Actor"},
                    {"name": "Object", "id": "Object"},
                    {"name": "Score", "id": "Score"},
                    {"name": "Mission Level", "id": "Mission Level"},
                   
                ],
                data=df.to_dict('records'),
                page_size=10,
                style_table={'height': '400px', 'overflowY': 'auto'},
                style_cell={'textAlign': 'center', 'padding': '10px'},
                style_data_conditional=[
                    {
                        'if': {'row_index': 'odd'},
                        'backgroundColor': 'rgb(248, 248, 248)',
                    }
                ]
            ),
        ], style={'width': '70%', 'float': 'right', 'padding': '20px'}),
    ], style={'display': 'flex'}),
])

@app.callback(
    [Output('table', 'data'),
     Output('score-evolution', 'figure')],
    [Input('refresh-button', 'n_clicks'),
     Input('verb-filter', 'value'),
     Input('score-filter', 'value'),
     Input('mission-filter', 'value')]
)
def update_table_and_graph(n_clicks, selected_verbs, score_filter, selected_levels):
    data = fetch_lrs_data()
    df = process_data(data)

    if selected_verbs:
        df = df[df["Verb"].isin(selected_verbs)]

    if 'with_score' in score_filter:
        df = df[df["Score"].notnull()]

    if selected_levels:
        df = df[df["Mission Level"].isin(selected_levels)]

    mission_grouped = df.groupby("Mission Level")["Score"].max().reset_index()
    mission_grouped = mission_grouped.sort_values(by="Mission Level", ascending=True)

    fig = px.bar(
        mission_grouped,
        x="Mission Level",
        y="Score",
        title="Score final par niveau de mission",
        labels={"Mission Level": "Niveau de Mission", "Score": "Score Final"},
        color="Mission Level",
    )

    return df.to_dict('records'), fig

if __name__ == '__main__':
    app.run_server(debug=True)
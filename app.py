import requests
import pandas as pd
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State

# Function to fetch data from LRS
def fetch_lrs_data(name):
    endpoint = "https://lrsels.lip6.fr/data/xAPI/statements"
    headers = {
        "X-Experience-API-Version": "1.0.3"
    }
    auth = ("9fe9fa9a494f2b34b3cf355dcf20219d7be35b14", "b547a66817be9c2dbad2a5f583e704397c9db809")

    params = {
        "agent": f'{{"account": {{"homePage": "https://www.lip6.fr/mocah/", "name": "{name}"}}}}',
        "limit": 100
    }

    response = requests.get(endpoint, headers=headers, auth=auth, params=params)

    if response.status_code == 200:
        data = response.json()["statements"]
        return data
    else:
        raise Exception(f"Error fetching data: {response.status_code}, {response.text}")


# Process data

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


app.layout = html.Div([
    dcc.Location(id='url', refresh=False),  # For dynamic URL handling

    # Page title
    html.H1(id='dashboard-title', children="Suivre ta progression"),

    # User Input or Logout Button
    html.Div(id='login-section', children=[
        html.Label("Entre ton code SPY :"),
        dcc.Input(id='user-id', type='text', placeholder="(ex : C2ED0A43)"),
        html.Button("Valider", id='submit-button', n_clicks=0)
    ]),

    # Hidden div to store user name
    html.Div(id='stored-name', style={'display': 'none'}),

    # Logout Button (outside dashboard content)
    html.Div(
        id='logout-container',
        style={'display': 'none'},  # Initially hidden
        children=[
            html.Button("Déconnexion", id='logout-button', n_clicks=0)
        ]
    ),

    # Dashboard content (hidden by default)
    html.Div(
        id='dashboard-content',
        style={'display': 'none'},  # Initially hidden
        children=[
            html.Button("Rafraîchir", id='refresh-button', n_clicks=0),

            html.Label("Filtrer par Verb:"),
            dcc.Dropdown(
                id='verb-filter',
                options=[],
                multi=True,
                placeholder="Sélectionnez un ou plusieurs verbes"
            ),

            dash_table.DataTable(
                id='table',
                columns=[
                    {"name": "Timestamp", "id": "Timestamp"},
                    {"name": "Verb", "id": "Verb"},
                    {"name": "Actor", "id": "Actor"},
                    {"name": "Object", "id": "Object"}
                ],
                data=[],
                page_size=10
            )
        ]
    ),
])


@app.callback(
    [Output('stored-name', 'children'),
     Output('login-section', 'style'),
     Output('dashboard-content', 'style'),
     Output('logout-container', 'style'),
     Output('dashboard-title', 'children')],
    [Input('submit-button', 'n_clicks'),
     Input('logout-button', 'n_clicks')],
    [State('user-id', 'value')]
)
def handle_login_logout(submit_clicks, logout_clicks, user_id):
    # If logout button is clicked
    if logout_clicks > 0:
        return "", {'display': 'block'}, {'display': 'none'}, {'display': 'none'}, "Suivre ta progression"

    # If submit button is clicked and user ID is provided
    if submit_clicks > 0 and user_id:
        return user_id, {'display': 'none'}, {'display': 'block'}, {'display': 'block'}, f"Dashboard : {user_id}"

    # Default state
    return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update



@app.callback(
    [Output('verb-filter', 'options'),
     Output('table', 'data')],
    [Input('stored-name', 'children'),
     Input('refresh-button', 'n_clicks')],
    [State('verb-filter', 'value')]
)
def update_dashboard(name, n_clicks, selected_verbs):
    if name:
        try:
            # Fetch and process data
            data = fetch_lrs_data(name)
            df = process_data(data)

            # Filter data if needed
            if selected_verbs:
                df = df[df["Verb"].isin(selected_verbs)]

            # Prepare dropdown options
            verb_options = [{"label": verb, "value": verb} for verb in df["Verb"].unique()]

            return verb_options, df.to_dict('records')
        except Exception as e:
            return [], []
    return [], []



if __name__ == '__main__':
    app.run_server(debug=True)

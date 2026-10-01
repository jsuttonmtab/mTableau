from dash import html, dcc, ALL
import dash_bootstrap_components as dbc
from utils.auth import list_users_admin

def build_users_layout():
    users = list_users_admin()
    user_rows = []
    for u in users:
        user_rows.append(
            html.Tr([
                html.Td(u["name"], style={"fontSize": "13px"}),
                html.Td(u["email"], style={"fontSize": "13px"}),
                html.Td("Yes" if u["is_admin"] else "No", style={"fontSize": "13px"}),
                html.Td([
                    dbc.Button("Reset PW",
                              id={"type": "reset-pw-btn", "index": u["email"]},
                              color="warning", size="sm", outline=True,
                              className="me-1",
                              style={"fontSize": "10px", "padding": "1px 6px"}),
                    dbc.Button("Delete",
                              id={"type": "delete-user-btn", "index": u["email"]},
                              color="danger", size="sm", outline=True,
                              style={"fontSize": "10px", "padding": "1px 6px"}),
                ], style={"whiteSpace": "nowrap"}),
            ])
        )
    return html.Div([
        html.H4("User Management", className="mb-4 fw-bold"),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H6("Users", className="mb-0 fw-bold")),
                    dbc.CardBody([
                        html.Table([
                            html.Thead(html.Tr([
                                html.Th("Name", style={"fontSize": "12px"}),
                                html.Th("Email", style={"fontSize": "12px"}),
                                html.Th("Admin", style={"fontSize": "12px"}),
                                html.Th("Actions", style={"fontSize": "12px"}),
                            ])),
                            html.Tbody(user_rows, id="users-table-body"),
                        ], className="table table-sm table-hover"),
                        html.Div(id="user-action-msg", className="mt-2",
                                style={"fontSize": "12px"}),
                    ])
                ], className="mb-4 shadow-sm"),
            ], width=8),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H6("Add User", className="mb-0 fw-bold")),
                    dbc.CardBody([
                        dbc.Label("Name", size="sm", className="fw-bold"),
                        dbc.Input(id="new-user-name", size="sm",
                                 placeholder="Full name", className="mb-2"),
                        dbc.Label("Email", size="sm", className="fw-bold"),
                        dbc.Input(id="new-user-email", size="sm",
                                 placeholder="user@mtab.com", className="mb-2"),
                        dbc.Label("Temp Password", size="sm", className="fw-bold"),
                        dbc.Input(id="new-user-password", size="sm",
                                 type="password", placeholder="Initial password",
                                 className="mb-2"),
                        dbc.Checkbox(id="new-user-admin", label="Admin",
                                    value=False, className="mb-3",
                                    style={"fontSize": "12px"}),
                        dbc.Button("Add User", id="add-user-btn",
                                  color="primary", size="sm"),
                        html.Div(id="add-user-msg", className="mt-2",
                                style={"fontSize": "12px"}),
                    ])
                ], className="mb-4 shadow-sm"),
            ], width=4),
        ]),
    ], className="p-4")

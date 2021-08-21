import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
import plotly.graph_objs
from dash.dependencies import Output, Input, State
import secrets
import flask
from flask_login import login_user, LoginManager, UserMixin, logout_user, current_user
import datetime

from config import Config
from analytics import PortfolioAnalytics

secret_key = secrets.token_hex(24)


class User(UserMixin):
    def __init__(self, username):
        self.id = username


################################################################################################################
#                                                  Layouts                                                     #
################################################################################################################


# Login screen
def create_login_layout():
    username_input = dbc.FormGroup(
        [
            dbc.Label("Username", html_for='username_input'),
            dbc.Input(type='text', id='username_input', placeholder='Enter username', autoFocus=True),
        ]
    )
    password_input = dbc.FormGroup(
        [
            dbc.Label('Password', html_for='password_input'),
            dbc.Input(
                type='password',
                id='password_input',
                placeholder='Enter password'
            ),
            dbc.FormText(
                'Forgot your password? Too bad...', color='secondary'
            )
        ]
    )

    return html.Div(
        [dcc.Location(id='url_login', refresh=True),
         dbc.Container(dbc.Row(dbc.Col(dbc.Card(
             [
                 html.Div([
                     html.H4('FundLess', className='card-title'),
                     html.H6('Please login', className='card-subtitle')
                 ], style={'textAlign': 'center'}),
                 dbc.Form([
                     username_input,
                     password_input,
                     dbc.Button('Login', color='primary', id='login_button', block=True),
                     dbc.Alert('Incorrect username or password', id='output-state', is_open=False, color='danger',
                               style={'margin': '1rem'})
                 ], id='login_form'),
             ],
             body=True,
             # style={'padding-top': '15%'}
             style={'width': '22rem',
                    # 'height': '26rem'
                    }
         ), align='center', width='auto', style={'height': '100%', 'padding-top': '15%'}),
             justify='center'),
             # style={'height': '100vh', 'width': '100vh'}
         )
         ],
        # style={'align-items': 'center', 'justify-content': 'center', 'display': 'flex', 'padding-top': '5%',
        #        'width': '20rem'}
    )


# Failed Login
def create_failed_layout():
    return html.Div([html.Div([html.H4('Log in Failed. Please try again.'),
                               html.Br(),
                               html.Div([create_login_layout()]),
                               ], style=dict(textAlign='center'))  # end div
                     ])  # end div


# Logout screen
def create_logout_layout():
    return html.Div(dbc.Row([
        dbc.Card(
            [html.Div(html.H4('You have been logged out')),
             html.Div(html.H6('- Good Bye -')),
             dbc.Button('Login', href='/login', color='primary')],
            style={'padding': '2rem 2rem'}
        )
    ], justify='center', style={'padding-top': '15%'}), style=dict(textAlign='center'))  # end div


# Sidebar
def create_page_with_sidebar(content):
    navbar = dbc.NavbarSimple(
        children=[
            dbc.Select(
                id='chart_time_range',
                options=[
                    {'label': '1 Day', 'value': 'day'},
                    {'label': '1 Week', 'value': 'week'},
                    {'label': '1 Month', 'value': 'month'},
                    {'label': '6 Month', 'value': '6month'},
                    {'label': '1 Year', 'value': 'year'},
                    {'label': 'Since Buy', 'value': 'buy'}
                ],
                value='buy',
                placeholder='Select time range',
                bs_size='sm',

            ),
            dbc.Button(id='user-status-div', color='primary'),

        ],
        brand="FundLess",
        brand_href="/dashboard",
        color="primary",
        dark=True,
    )



    # the style arguments for the sidebar. We use position:fixed and a fixed width
    SIDEBAR_STYLE = {
        "position": "fixed",
        "top": 0,
        "left": 0,
        "bottom": 0,
        "width": "16rem",
        "padding": "2rem 1rem",
        "background-color": "#f8f9fa",
    }

    # the styles for the main content position it to the right of the sidebar and
    # add some padding.
    CONTENT_STYLE = {
        "margin-left": "18rem",
        "margin-right": "2rem",
        "padding": "2rem 1rem",
    }

    sidebar = html.Div(
        [
            html.H2("FundLess", className="display-4"),
            html.Hr(),
            html.P(
                "Crypto Portfolio", className="lead"
            ),
            dbc.Nav(
                [
                    dbc.NavLink("Dashboard", href="/dashboard", active="exact"),
                    dbc.NavLink("Savings Plan", href="/page-2", active="exact"),
                ],
                vertical=True,
                pills=True,
            ),
        ],
        style=SIDEBAR_STYLE,
    )

    page = html.Div([html.Div(navbar,
                              # style={"margin-left": "16rem"}
                              ),
                     html.Div(children=content,
                              # style=CONTENT_STYLE
                              )
                     ])
    return html.Div([page])

################################################################################################################
#                                            Dashboard Class                                                   #
################################################################################################################
class Dashboard:
    app: dash.Dash
    analytics: PortfolioAnalytics
    config: Config

    def __init__(self, config: Config, analytics: PortfolioAnalytics):
        server = flask.Flask(__name__)
        external_stylesheets = [dbc.themes.LITERA]
        self.app = dash.Dash(name=__name__, external_stylesheets=external_stylesheets, server=server,
                             title='FundLess', update_title='FundLess...', suppress_callback_exceptions=False,
                             meta_tags=[
                                 {"name": "viewport", "content": "width=device-width, initial-scale=1"},
                             ]
                             )
        self.config = config
        self.analytics = analytics

        # Preload data heavy figures
        self.allocation_chart = self.analytics.allocation_pie(title=False)
        self.performance_chart = self.analytics.performance_chart(title=False)

        # config flask login
        server.config.update(SECRET_KEY=secret_key)
        # Login manager object will be used to login / logout users
        login_manager = LoginManager()
        login_manager.init_app(server)
        login_manager.login_view = '/login'



        # Main Layout
        self.app.layout = html.Div([
            dcc.Location(id='url', refresh=False),
            dcc.Location(id='redirect', refresh=True),
            dcc.Store(id='login-status', storage_type='session'),
            # html.Div(id='user-status-div', style=dict(textAlign='right')),
            html.Div(id='page-content'),
            dcc.Interval('file_update_interval', 60 * 1000, n_intervals=0),
            html.Div(id='dummy', style={'display': 'none'})
        ])

        @login_manager.user_loader
        def load_user(username):
            """
                This function loads the user by user id. Typically this looks up the user from a user database.
                We won't be registering or looking up users in this example, since we'll just login using LDAP server.
                So we'll simply return a User object with the passed in username.
            """
            return User(username)

        # add callback for toggling the collapse of navbar on small screens
        @self.app.callback(
            Output("navbar-collapse", "is_open"),
            [Input("navbar-toggler", "n_clicks")],
            [State("navbar-collapse", "is_open")],
        )
        def toggle_navbar_collapse(n, is_open):
            if n:
                return not is_open
            return is_open

        # Login callback
        @self.app.callback(
            [Output('url_login', 'pathname'), Output('output-state', 'is_open')],
            [Input('login_form', 'n_submit')],
            [State('username_input', 'value'), State('password_input', 'value')]
        )
        def login_button_click(n, username, password):
            if n:
                if n > 0:
                    if username == 'test' and password == 'test':
                        user = User(username)
                        login_user(user)
                        return '/dashboard', False
                    else:
                        return '/login', True
            else:
                return '/login', False

        # Update csv files
        @self.app.callback(Output('dummy', 'children'), Input('file_update_interval', 'n_intervals'))
        def update_files(n):
            self.analytics.update_trades_df()
            return ''

        # Allocation chart update
        @self.app.callback(Output('allocation_chart', 'figure'), Input('allocation-interval', 'n_intervals'))
        def update_allocation_chart(n):
            self.allocation_chart = analytics.allocation_pie(title=False)
            return self.allocation_chart

        # Performance chart update
        @self.app.callback(Output('performance_chart', 'figure'), Input('performance-interval', 'n_intervals'),
                           Input('chart_time_range', 'value'))
        def update_performance_chart(_, value):
            now = datetime.datetime.now()
            if value == 'day':
                timestamp = (now - datetime.timedelta(days=1)).timestamp()
            elif value == 'week':
                timestamp = (now - datetime.timedelta(weeks=1)).timestamp()
            elif value == 'month':
                timestamp = (now - datetime.timedelta(days=30)).timestamp()
            elif value == '6month':
                timestamp = (now - datetime.timedelta(days=182)).timestamp()
            elif value == 'year':
                timestamp = (now - datetime.timedelta(days=365)).timestamp()
            else:
                timestamp = None
            self.performance_chart = analytics.performance_chart(from_timestamp=timestamp, title=False)
            return self.performance_chart

        # Check login status to show correct login/logout button
        @self.app.callback(Output('user-status-div', 'children'), Output('user-status-div', 'href'), Output('login-status', 'data'),
                           [Input('url', 'pathname')])
        def login_status(url):
            """ callback to display login/logout link in the header """
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated \
                    and url != '/logout':  # If the URL is /logout, then the user is about to be logged out anyways
                return 'Logout', '/logout', current_user.get_id()
            elif url == '/login':
                # do not show login button, if already on login screen
                return None, None, 'loggedout'
            else:
                return 'Login', '/login', 'loggedout'

        # Page forward callback
        @self.app.callback(Output('page-content', 'children'), Output('redirect', 'pathname'),
                           [Input('url', 'pathname')])
        def display_page(pathname):
            """ callback to determine layout to return """
            view = None
            url = dash.no_update
            if pathname == '/login':
                if current_user.is_authenticated:
                    view = 'Already logged in, forwarding...'
                    url = '/dashboard'
                else:
                    view = create_login_layout()
            elif pathname == '/dashboard':
                if current_user.is_authenticated:
                    view = create_page_with_sidebar(self.create_dashboard())
                else:
                    view = create_failed_layout()
            elif pathname == '/logout':
                if current_user.is_authenticated:
                    logout_user()
                    view = create_logout_layout()
                else:
                    view = create_login_layout()
                    url = '/login'
            else:  # You could also return a 404 "URL not found" page here
                if current_user.is_authenticated:
                    view = create_page_with_sidebar(self.create_dashboard())
                else:
                    view = 'Redirecting to login...'
                    url = '/login'
            return view, url

    def run_dashboard(self):
        self.app.run_server(host='0.0.0.0', port=80,
                            debug=False)  # as the dashboard runs in a separate thread, debug mode is not supported

    ################################################################################################################
    #                                                  Layouts                                                     #
    ################################################################################################################

    # Main Dashboard
    def create_dashboard(self):

        symbols, amounts, values, allocations = self.analytics.index_balance()
        net_worth = values.sum()
        performance = self.analytics.performance(net_worth)
        invested = self.analytics.invested()
        currency_symbol = self.config.trading_bot_config.base_currency.values[1]

        if performance > 0:
            color = 'green'
            prefix = '+'
        else:
            color = 'red'
            prefix = '-'

        # Info Cards
        card_row_1 = dbc.Row(
            [
                dbc.Col(
                    dbc.Card([
                        dbc.CardHeader("Portfolio Worth"),
                        dbc.CardBody(
                            [
                                html.H5(f'{net_worth:.2f} {currency_symbol}'),
                                html.H6(f'{prefix}{performance:.2%}', style={'color': color})
                            ]
                        )
                    ],
                        # color=color,
                        outline=True
                    ),
                    sm=12, md=6, style={'margin': '1rem 0rem'}
                ),
                dbc.Col(
                    dbc.Card([
                        dbc.CardHeader("Invested"),
                        dbc.CardBody(
                            [
                                html.H5(f'{invested:.2f} {currency_symbol}'),
                                html.H6(f'{prefix}{net_worth - invested:.2f} {currency_symbol}', style={'color': color})
                            ]
                        )
                    ],
                        # color=color,
                        outline=True
                    ),
                    sm=12, md=6, style={'margin': '1rem 0rem'}
                ),
            ],
            className='mb-6',
        )
        card_row_2 = dbc.Row(
            [
                dbc.Col(
                    dbc.Card([
                        dbc.CardHeader("Top Gainers"),
                        dbc.CardBody(
                            [html.P('Test')]
                        )
                    ]),
                    sm=12, md=6, style={'margin': '1rem 0rem'}
                ),
                dbc.Col(
                    dbc.Card([
                        dbc.CardHeader("News"),
                        dbc.CardBody(
                            [html.P('Test')]
                        )
                    ]),
                    sm=12, md=6, style={'margin': '1rem 0rem'}
                )
            ],
            className='mb-6',
        )

        info_cards = [card_row_1, card_row_2]

        # info_cards = dbc.CardGroup(
        #     [
        #         dbc.Card([
        #             dbc.CardHeader("Portfolio Worth"),
        #             dbc.CardBody(
        #                 [
        #                     html.H5(f'{net_worth:.2f} {currency_symbol}'),
        #                     html.H6(f'{prefix}{performance:.2%}', style={'color': color})
        #                 ]
        #             )
        #         ],
        #             color=color,
        #             outline=True
        #         ),
        #         dbc.Card([
        #             dbc.CardHeader("Invested"),
        #             dbc.CardBody(
        #                 [
        #                     html.H5(f'{invested:.2f} {currency_symbol}'),
        #                     html.H6(f'{prefix}{net_worth - invested:.2f} {currency_symbol}', style={'color': color})
        #                 ]
        #             )
        #         ],
        #             color=color,
        #             outline=True
        #         ),
        #         dbc.Card([
        #             dbc.CardHeader("Top Gainers"),
        #             dbc.CardBody(
        #                 [html.P('Test')]
        #             )
        #         ]),
        #         dbc.Card([
        #             dbc.CardHeader("News"),
        #             dbc.CardBody(
        #                 [html.P('Test')]
        #             )
        #         ])
        #     ]
        # )

        return html.Div(children=[
            # html.H1('FundLess Dashboard', style=dict(textAlign='center')),
            # update allocation chart every 20 seconds
            dcc.Interval(id='allocation-interval', interval=20 * 1000, n_intervals=0),
            # update performance chart every 5 minutes
            dcc.Interval(id='performance-interval', interval=5 * 60 * 1000, n_intervals=0),
            dbc.Container([
                dbc.Row([
                    dbc.Col([
                        dcc.Graph(
                            id='allocation_chart',
                            figure=self.allocation_chart,
                            config={
                                'displayModeBar': False
                            }
                        ),

                    ],
                        lg=4,
                        # style={'background-color': 'blue'}
                    ),
                    dbc.Col(
                        info_cards,
                        lg=8,
                        # style={'background-color': 'blue'}
                    )
                ], justify='center', no_gutters=False, align='center'),

                dbc.Row(
                    [
                        dbc.Col([
                            dcc.Graph(
                                id='performance_chart',
                                figure=self.performance_chart,
                                config={
                                    'displayModeBar': False
                                }
                            )
                        ],
                            xs=12,
                            # style={'background-color': 'blue'}
                        )
                    ],
                    justify='center', no_gutters=False
                )],
                fluid=True),
        ])

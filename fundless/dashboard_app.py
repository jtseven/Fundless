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

def create_dashboard(allocation_chart: plotly.graph_objs.Figure, performance_chart: plotly.graph_objs.Figure):
    # Main Dashboard
    return html.Div(children=[
        html.H1('FundLess Dashboard', style=dict(textAlign='center')),
        # update allocation chart every 20 seconds
        dcc.Interval(id='allocation-interval', interval=20 * 1000, n_intervals=0),
        # update performance chart every 5 minutes
        dcc.Interval(id='performance-interval', interval=5 * 60 * 1000, n_intervals=0),
        dbc.Container(
            [
                dbc.Row([
                    dbc.Col(
                        dcc.Graph(
                            id='allocation_chart',
                            figure=allocation_chart,
                            config={
                                'displayModeBar': False
                            }
                        ),
                        width=4,
                    ),
                    dbc.Col([
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
                            placeholder='Select time range'
                        ),
                        dcc.Graph(
                            id='performance_chart',
                            figure=performance_chart,
                            config={
                                'displayModeBar': False
                            }
                        )],
                        width=8
                    )
                ],
                    align='center',
                    justify='center')
            ])
    ])


# Login screen
def create_login_layout():
    username_input = dbc.FormGroup(
        [
            dbc.Label("Username", html_for='username_input'),
            dbc.Input(type='text', id='username_input', placeholder='Enter username'),
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
                     dbc.Button('Login', color='primary', id='login_button', block=True)
                 ], id='login_form'),
                 html.Div(children='', id='output-state')
             ],
             body=True,
             # style={'padding-top': '15%'}
             # style={'width': '6rem'}
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
    return html.Div([html.Div(html.H3('You have been logged out')),
                     html.Div(html.H3('- Good Bye -'))], style=dict(textAlign='center'))  # end div


# Sidebar


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
        self.allocation_chart = self.analytics.allocation_pie()
        self.performance_chart = self.analytics.performance_chart()

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
            html.Div(id='user-status-div', style=dict(textAlign='right')),
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

        # Login callback
        @self.app.callback(
            [Output('url_login', 'pathname'), Output('output-state', 'children')],
            [Input('login_form', 'n_submit')],
            [State('username_input', 'value'), State('password_input', 'value')]
        )
        def login_button_click(n, username, password):
            if n:
                if n > 0:
                    if username == 'test' and password == 'test':
                        user = User(username)
                        login_user(user)
                        return '/success', ''
                    else:
                        return '/login', 'Incorrect username or password'
            else:
                return '/login', ''

        # Update csv files
        @self.app.callback(Output('dummy', 'children'), Input('file_update_interval', 'n_intervals'))
        def update_files(n):
            self.analytics.update_trades_df()
            return ''

        # Allocation chart update
        @self.app.callback(Output('allocation_chart', 'figure'), Input('allocation-interval', 'n_intervals'))
        def update_allocation_chart(n):
            self.allocation_chart = analytics.allocation_pie()
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
            self.performance_chart = analytics.performance_chart(from_timestamp=timestamp)
            return self.performance_chart

        # Check login status to show correct login/logout button
        @self.app.callback(Output('user-status-div', 'children'), Output('login-status', 'data'),
                           [Input('url', 'pathname')])
        def login_status(url):
            """ callback to display login/logout link in the header """
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated \
                    and url != '/logout':  # If the URL is /logout, then the user is about to be logged out anyways
                return dbc.Button('logout', href='/logout', color='primary'), current_user.get_id()
            elif url == '/login':
                # do not show login button, if already on login screen
                return None, 'loggedout'
            else:
                return dbc.Button('login', href='/login', color='primary'), 'loggedout'

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
                    url = '/success'
                else:
                    view = create_login_layout()
            elif pathname == '/success':
                if current_user.is_authenticated:
                    view = create_dashboard(self.allocation_chart, self.performance_chart)
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
                    view = create_dashboard(self.allocation_chart, self.performance_chart)
                else:
                    view = 'Redirecting to login...'
                    url = '/login'
            return view, url

    def run_dashboard(self):
        self.app.run_server(host='0.0.0.0', port=80,
                            debug=False)  # as the dashboard runs in a separate thread, debug mode is not supported

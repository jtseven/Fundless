import dash
from dash import dcc
from dash import html
import dash_bootstrap_components as dbc
import flask
from dash_extensions.enrich import NoOutputTransform, DashProxy, Input, Output, State, \
    MultiplexerTransform, MATCH, ALL, ClientsideFunction
from dash_extensions import DeferScript
from gevent.pywsgi import WSGIServer
from flask import render_template, redirect
import logging
import traceback

# local imports
from config import Config
from analytics import PortfolioAnalytics
import layouts
from login import LoginProvider
from constants import Auth0EnvNames, STABLE_COINS

logger = logging.getLogger(__name__)

APP_URL = '/app/'


def app_path(page_name: str):
    if len(page_name) > 0:
        return APP_URL + page_name
    else:
        return APP_URL


################################################################################################################
#                                            Dashboard Class                                                   #
################################################################################################################
class Dashboard:
    app: dash.Dash
    analytics: PortfolioAnalytics
    config: Config

    def __init__(self, config: Config, analytics: PortfolioAnalytics):
        server = flask.Flask(__name__)
        server.secret_key = Auth0EnvNames.SECRET_KEY
        external_stylesheets = [
            dbc.themes.LITERA,  # FLATLY, LITERA, YETI
            'https://unpkg.com/bootstrap-table@1.18.3/dist/bootstrap-table.min.css',
        ]
        external_scripts = [
            'https://code.jquery.com/jquery-3.6.0.slim.js',
            'https://cdn.jsdelivr.net/npm/bootstrap@5.1.1/dist/js/bootstrap.bundle.min.js',
            'https://unpkg.com/bootstrap-table@1.18.3/dist/bootstrap-table.min.js',
        ]
        self.server = server
        self.config = config
        self.analytics = analytics
        self.login_provider = LoginProvider(config.dashboard_config, self.server, config.secrets)

        # Preload data heavy figures
        self.allocation_chart = self.analytics.allocation_pie(title=False)
        self.history_chart = self.analytics.value_history_chart(title=False)
        self.performance_chart = self.analytics.performance_chart(title=False)

        ########################################################################################################
        #                                        Static Routes                                                 #
        ########################################################################################################

        @server.route('/', strict_slashes=False)
        @server.route('/home', strict_slashes=False)
        def home():
            return render_template('home.html')

        @server.route('/callback')
        def callback_handling():
            # Handles response from token endpoint
            return self.login_provider.auth0_callback()

        @server.route('/login', methods=['POST', 'GET'])
        def login():
            return self.login_provider.login_page()

        @server.route('/app/<subpath>', strict_slashes=False)
        @self.login_provider.requires_auth
        def view_dashboard_subpath(subpath):
            return self.app.index()

        @server.route('/app', strict_slashes=False)
        @self.login_provider.requires_auth
        def view_dashboard():
            return self.app.index()

        @server.route('/dashboard', strict_slashes=False)
        @self.login_provider.requires_auth
        def view_dashboard_again():
            return redirect('/app')

        @server.route('/logout')
        @server.route('/app/logout')
        @self.login_provider.requires_auth
        def logout():
            return self.login_provider.logout()

        self.app = DashProxy(name=__name__, external_stylesheets=external_stylesheets, server=server,
                             title='Fundless', update_title='Fundless...', suppress_callback_exceptions=False,
                             meta_tags=[
                                 {"name": "viewport", "content": "width=device-width, initial-scale=1",
                                  "apple-mobile-web-app-capable": "yes",
                                  "apple-mobile-web-app-status-bar-style": "default"},
                             ],
                             external_scripts=external_scripts,
                             url_base_pathname=APP_URL,
                             transforms=[NoOutputTransform(), MultiplexerTransform()],
                             )

        if config.dashboard_config.domain_name != 'localhost':
            server.config.update(SERVER_NAME=f'{config.dashboard_config.domain_name}')

        manifest_url = self.app.get_asset_url('manifest.json')
        self.app.index_string = '''
        <!DOCTYPE html>
        <html>
            <head>
                {%metas%}
                <link rel="manifest" href=''' + manifest_url + '''>
                <link rel="shortcut icon" href="/app/assets/icons/128.png">
                <link rel="apple-touch-icon" href="/app/assets/icons/128.png">
                <title>{%title%}</title>
                {%favicon%}
                {%css%}
                <script src="https://kit.fontawesome.com/830ba245ba.js" crossorigin="anonymous"></script>
            </head>
            <body>
                {%app_entry%}
                <footer>
                    {%config%}
                    {%scripts%}
                    {%renderer%}
                </footer>
            </body>
        </html>
        '''

        # Main Layout
        self.app.layout = html.Div([
            dcc.Location(id='url', refresh=False),
            dcc.Location(id='redirect', refresh=True),
            layouts.create_page_with_sidebar(),
            DeferScript(src='assets/custom.js')
        ])

        self.app.validation_layout = html.Div([
            layouts.create_dashboard(self.analytics, self.allocation_chart),
            layouts.create_holdings_page(self.analytics),
            layouts.create_strategy_page(self.analytics),
            layouts.create_trades_page(self.analytics),
            layouts.create_not_implemented(''),
            layouts.create_404(''),
            self.app.layout,
        ])

        ########################################################################################################
        #                                          Callbacks                                                   #
        ########################################################################################################

        # Update pie chart and info cards (quick)
        @self.app.callback(Output('allocation_chart', 'figure'), Output('info_cards', 'children'),
                           Input('update-interval', 'n_intervals'))
        def update_charts_quick(_):
            self.allocation_chart = analytics.allocation_pie(title=False)
            info_cards = layouts.create_info_cards(self.analytics)

            return self.allocation_chart, info_cards

        @self.app.callback(Output('holdings_table', 'children'),
                           Input('holdings-update-interval', 'n_intervals'))
        def update_holdings(_):
            return layouts.create_holdings_table(self.analytics)

        # Update performance and history charts
        @self.app.callback(Output('chart', 'figure'),
                           Input('update-interval', 'n_intervals'),
                           Input('chart_time_range', 'value'), Input('chart_tabs', 'active_tab'))
        def update_charts_slow(_, chart_range, active_tab):
            try:
                timestamp = analytics.get_timestamp(chart_range)
                self.performance_chart = self.analytics.performance_chart(from_timestamp=timestamp, title=False)
                self.history_chart = analytics.value_history_chart(from_timestamp=timestamp, title=False)
                if active_tab == 'history_tab':
                    chart = self.history_chart
                elif active_tab == 'performance_tab':
                    chart = self.performance_chart
                else:
                    logger.warning('Invalid tab selected!')
                    chart = None
            except Exception:
                logger.error('Error in performance/history chart update callback!')
                logger.error(traceback.format_exc())
                raise
            return chart

        @self.app.callback(Input('accounting_currency_select', 'value'))
        def set_base_currency(value):
            if self.config.trading_bot_config.base_currency.value.lower() != value.lower():
                logger.debug('Updating config!')
                self.config.trading_bot_config.base_currency = value  # this also changes the config in analytics
                self.analytics.update_config(base_currency_changed=True)
                self.performance_chart = {}
                self.history_chart = {}
            else:
                logger.debug("Not updating config!")

        @self.app.callback(Input('quote_select', 'value'),
                           Output('coin_selection_buttons', 'children'),
                           Output('savings_plan_info', 'children'))
        def set_base_symbol(sym: str):
            if sym.lower() == self.config.trading_bot_config.base_symbol.lower():
                return dash.no_update
            self.config.trading_bot_config.base_symbol = sym
            return layouts.create_coin_buttons(analytics), layouts.savings_plan_info(analytics)

        @self.app.callback(Input('exchange_select', 'value'),
                           Output('savings_plan_info', 'children'),
                           Output('coin_selection_buttons', 'children'))
        def set_exchange(exchange: str):
            if exchange == self.config.trading_bot_config.exchange.value:
                return dash.no_update
            self.config.trading_bot_config.exchange = exchange
            self.analytics.exchanges.active = self.analytics.exchanges.authorized_exchanges[exchange]
            logger.info(f"Changed exchange to {self.analytics.exchanges.active.name}")
            return layouts.savings_plan_info(analytics, force_update=True), layouts.create_coin_buttons(analytics)

        @self.app.callback(Input('volume', 'value'),
                           Output('savings_plan_info', 'children'))
        def set_volume(vol):
            if vol is not None:
                if vol == self.config.trading_bot_config.savings_plan_cost:
                    return dash.no_update
                self.config.trading_bot_config.savings_plan_cost = float(vol)
            return layouts.savings_plan_info(analytics)

        @self.app.callback(
            Input('weighting', 'value'),
            Output('custom-weighting-collapse', 'is_open'),
            Output('chart_savings_plan_allocations', 'children')
        )
        def show_custom_form(weighting):
            self.config.trading_bot_config.portfolio_weighting = weighting
            if weighting == 'custom':
                return True, layouts.savings_plan_weight_chart(analytics)
            else:
                return False, layouts.savings_plan_weight_chart(analytics)

        @self.app.callback(Input('custom-weighting-collapse', 'is_open'),
                           Output('custom_form', 'children'))
        def get_custom_weights(is_open):
            if is_open:
                return layouts.create_weighting_sliders(analytics)
            else:
                return dash.no_update

        @self.app.callback(
            Input({'type': 'btn-coin-select', 'index': MATCH}, 'n_clicks'),
            State({'type': 'btn-coin-select', 'index': MATCH}, 'active'),
            Output({'type': 'btn-coin-select', 'index': MATCH}, 'active'),
        )
        def update_coin_selection_active_state(n_clicks, active):
            if n_clicks is not None:
                if n_clicks > 0:
                    return not active
            return dash.no_update

        @self.app.callback(
            Input({'type': 'btn-coin-select', 'index': ALL}, 'n_clicks'),
            State({'type': 'btn-coin-select', 'index': ALL}, 'value'),
            State({'type': 'btn-coin-select', 'index': ALL}, 'active'),
            Output('coin_selection_buttons', 'children'),
            Output('savings_plan_info', 'children'),
            Output('chart_savings_plan_allocations', 'children'),
            Output('dropdown_add_coin', 'options')
        )
        def update_index_coins(_, __, ___):
            n_clicks = dash.callback_context.triggered[0]['value']
            if n_clicks is None:
                return dash.no_update
            if n_clicks < 1:
                return dash.no_update

            prop_id = dash.callback_context.triggered[0]['prop_id']
            value_key = prop_id[:prop_id.rfind('.')] + '.value'
            active_key = prop_id[:prop_id.rfind('.')] + '.active'
            value = str(dash.callback_context.states[value_key])
            active = bool(dash.callback_context.states[active_key])

            index = self.config.trading_bot_config.cherry_pick_symbols
            additional_options = dash.no_update
            buttons = dash.no_update
            if not active:
                logger.info(f'Adding {value} to the index')
                # add coin to index
                if value not in index:
                    self.config.trading_bot_config.cherry_pick_symbols.append(value)
                    self.analytics.update_config(index_changed=True)
                    buttons = layouts.create_coin_buttons(analytics)
                else:
                    return dash.no_update
            else:
                # remove coin from index
                logger.info(f'Removing {value} from the index')
                if value in index:
                    self.config.trading_bot_config.cherry_pick_symbols.remove(value)
                    self.analytics.update_config(index_changed=True)
                    top_9 = analytics.top_n(9)
                    if value not in top_9:
                        additional_options = [{'label': analytics.get_coin_name(sym), 'value': sym} for sym in
                                              analytics.markets.symbol.values
                                              if sym not in self.config.trading_bot_config.cherry_pick_symbols
                                              and sym not in top_9
                                              and sym.upper() not in STABLE_COINS
                                              and analytics.coin_available_on_exchange(sym)
                                              ]
                buttons = layouts.create_coin_buttons(analytics)
            return buttons, layouts.savings_plan_info(analytics), \
                   layouts.savings_plan_weight_chart(analytics), additional_options

        @self.app.callback(
            Input('dropdown_add_coin', 'value'),
            State('dropdown_add_coin', 'options'),
            Output('dropdown_add_coin', 'value'),
            Output('dropdown_add_coin', 'options'),
            Output('coin_selection_buttons', 'children')
        )
        def add_coin_selection_button(sym, options):
            if sym is not None:
                self.config.trading_bot_config.cherry_pick_symbols.append(sym.lower())
                self.analytics.update_config(index_changed=True)
                new_options = [option for option in options if not option.get('value') == sym]
                return None, new_options, layouts.create_coin_buttons(analytics)
            return dash.no_update

        @self.app.callback(
            Output({'type': 'card-collapse', 'index': MATCH}, 'is_open'),
            Output({'type': 'card-toggle', 'index': MATCH}, 'children'),
            Input({'type': 'card-toggle', 'index': MATCH}, 'n_clicks'),
            State({'type': 'card-collapse', 'index': MATCH}, 'is_open')
        )
        def toggle_card(n_clicks, is_open):
            if n_clicks is not None:
                if n_clicks > 0:
                    return not is_open, 'Show all' if is_open else 'Show less'
            return dash.no_update, dash.no_update

        self.app.clientside_callback(
            # specify the callback with ClientsideFunction(<namespace>, <function name>)
            ClientsideFunction('ui', 'recompute_masonry'),
            # the Output, Input and State are passed in as with a regular callback
            Input({'type': 'card-collapse', 'index': ALL}, 'is_open')
        )

        # Page forward callback
        @self.login_provider.requires_auth
        @self.app.callback(Output('page-content', 'children'), Output('redirect', 'href'),
                           [Input('url', 'pathname')])
        def display_page(pathname):
            """ callback to determine layout to return """
            view = None
            # pathname = pathname + '/' if not pathname.endswith('/') else pathname
            forward = dash.no_update
            if not self.login_provider.is_authenticated():
                # Redirect to Login page here
                view = html.Div(['Redirecting to login...', html.Meta(httpEquiv='refresh', content='1')])
                forward = config.dashboard_config.domain_name
                return view, forward
            elif pathname == app_path(''):
                view = layouts.create_dashboard(self.analytics, self.allocation_chart)
                forward = 'dashboard'
            elif pathname == '/app':
                view = layouts.create_dashboard(self.analytics, self.allocation_chart)
                forward = 'app/dashboard'
            elif pathname == app_path('dashboard'):
                view = layouts.create_dashboard(self.analytics, self.allocation_chart)
            elif pathname == app_path('holdings'):
                view = layouts.create_holdings_page(self.analytics)
            elif pathname == app_path('strategy'):
                view = layouts.create_strategy_page(self.analytics)
            elif pathname == app_path('trades'):
                view = layouts.create_trades_page(self.analytics)
            elif pathname in ('/logout/', '/logout'):
                forward = 'logout'
                view = html.Div(['Logging out...', html.Meta(httpEquiv='refresh', content='1')])
            else:
                view = layouts.create_404(pathname)
            return view, forward

    def run_dashboard(self):
        if 'localhost' in self.config.dashboard_config.domain_name:
            logger.info('Webapp is available on localhost:3000')
            port = 3000
            host = self.config.dashboard_config.domain_name
            self.app.run_server(host=host, port=port, debug=False, use_reloader=False, dev_tools_hot_reload=False)
        else:
            port = 80
            host = '0.0.0.0'
            logger.info('Webapp is available on port 80')
            http_server = WSGIServer((host, port), self.server, )
            http_server.serve_forever()

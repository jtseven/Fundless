import dash
import dash_core_components as dcc
import dash_html_components as html

from config import Config
from analytics import PortfolioAnalytics


class Dashboard:
    app: dash.Dash
    analytics: PortfolioAnalytics
    config: Config

    def __init__(self, config: Config, analytics: PortfolioAnalytics):
        external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
        self.app = dash.Dash(name='PortfolioDashboard', external_stylesheets=external_stylesheets)
        self.app.title = 'FundLess Dashboard'
        self.config = config
        self.analytics = analytics

        self.app.layout = html.Div(children=[
            html.H1('FundLess Dashboard', style=dict(textAlign='center')),
            html.Div([
                html.Div([
                    dcc.Graph(
                        id='allocation_chart',
                        figure=self.analytics.allocation_pie(),
                        config={
                            'displayModeBar': False
                        }
                    )], className='four columns'),
                html.Div([
                    dcc.Graph(
                        id='performance_chart',
                        figure=self.analytics.performance_chart(),
                        config={
                            'displayModeBar': False
                        }
                    )], className='eight columns')
            ],
                className='row')
        ])

    def run_dashboard(self):
        self.app.run_server(host='0.0.0.0', port=80,
                            debug=False)  # as the dashboard runs in a separate thread, debug mode is not supported

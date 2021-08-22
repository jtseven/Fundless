import pandas as pd
from pathlib import Path
from pycoingecko import CoinGeckoAPI
from pydantic import validate_arguments
from pydantic.types import constr
import plotly.express as px
from typing import Tuple
import numpy as np
from time import time

from config import Config

csv_dtypes = {'buy_symbol': 'object', 'sell_symbol': 'object', 'price': 'float64',
              'amount': 'float64', 'cost': 'float64', 'fee': 'float64', 'fee_symbol': 'object'}
trades_cols = ['date', 'buy_symbol', 'sell_symbol', 'price', 'amount', 'cost', 'fee', 'fee_symbol']
index_cols = ['symbol', 'amount', 'value', 'current_price', 'allocation']

date_time_regex = '(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})'

# translate coingecko symbols to ccxt/binance symbols
coingecko_symbol_dict = {
    'miota': 'iota'
}

title_size = 28
text_size = 20
min_font_size = 10


class PortfolioAnalytics:
    trades_df: pd.DataFrame
    trades_file: Path
    index_df: pd.DataFrame
    history_df: pd.DataFrame
    coingecko: CoinGeckoAPI
    markets: pd.DataFrame  # CoinGecko Market Data

    last_market_update: float = 0  # seconds since epoch
    last_history_update: float = 0  # seconds since epoch

    def __init__(self, file_path, config: Config):
        self.config = config.trading_bot_config
        self.trades_file = Path(file_path)
        if self.trades_file.exists():
            self.update_trades_df()
        else:
            self.trades_df = pd.DataFrame(columns=trades_cols)
            self.trades_df.to_csv(self.trades_file, index=False)
        self.coingecko = CoinGeckoAPI()
        self.update_markets()

    def update_trades_df(self):
        self.trades_df = pd.read_csv(self.trades_file, dtype=csv_dtypes, parse_dates=['date'])
        self.trades_df['date'] = self.trades_df['date'].dt.tz_localize('UTC')

    def update_file(self):
        self.trades_df.sort_values('date', inplace=True)
        self.trades_df.to_csv(self.trades_file, index=False)

    def update_markets(self, force=False):
        if not force:
            # do not update, if last update less than 10 seconds ago
            if self.last_market_update > time()-10:
                print('stopped markets update')
                return

        # update market data from coingecko
        try:
            self.markets = pd.DataFrame.from_records(self.coingecko.get_coins_markets(
                vs_currency=self.config.base_currency.value, per_page=150))
            self.markets['symbol'] = self.markets['symbol'].str.lower()
        except Exception as e:
            print('Error while updating market data from CoinGecko:')
            print(e)
            raise e
        self.markets.replace(coingecko_symbol_dict, inplace=True)
        self.last_market_update = time()

        # update index portfolio value
        other = pd.DataFrame(index=self.config.cherry_pick_symbols)
        self.index_df = self.trades_df[['buy_symbol', 'amount', 'cost']].copy().groupby('buy_symbol').sum()
        self.index_df.index = self.index_df.index.str.lower()
        self.index_df = pd.merge(self.index_df, other, how='outer', left_index=True, right_index=True)
        self.index_df.fillna(value=0, inplace=True, axis='columns')
        self.index_df = self.markets[['symbol', 'current_price']].join(self.index_df, on='symbol', how='inner')
        self.index_df['value'] = self.index_df['current_price'] * self.index_df['amount']
        self.index_df['allocation'] = self.index_df['value'] / self.index_df['value'].sum()
        self.index_df['symbol'] = self.index_df['symbol'].str.upper()
        self.index_df['performance'] = self.index_df['value'] / self.index_df['cost'] - 1

    @validate_arguments
    def add_trade(self, date: constr(regex=date_time_regex),
                  buy_symbol: str, sell_symbol: str, price: float, amount: float,
                  cost: float, fee: float, fee_symbol: str):
        trade_dict = {'date': [date], 'buy_symbol': [buy_symbol.upper()], 'sell_symbol': [sell_symbol.upper()],
                      'price': [price], 'amount': [amount], 'cost': [cost], 'fee': [fee],
                      'fee_symbol': [fee_symbol.upper()]}
        self.update_trades_df()
        self.trades_df = self.trades_df.append(pd.DataFrame.from_dict(trade_dict), ignore_index=True)
        self.trades_df['date'] = pd.to_datetime(self.trades_df['date'], infer_datetime_format=True)
        self.update_file()

    def index_balance(self) -> Tuple:
        self.update_markets()
        self.index_df.sort_values(by='allocation', ascending=False, inplace=True)
        allocations = self.index_df['allocation'].values * 100
        symbols = self.index_df['symbol'].values
        values = self.index_df['value'].values
        amounts = self.index_df['amount'].values
        return symbols, amounts, values, allocations

    def performance(self, current_portfolio_value: float) -> float:
        amount_invested = self.trades_df['cost'].sum()
        return current_portfolio_value / amount_invested - 1

    def invested(self) -> float:
        return self.trades_df['cost'].sum()

    def allocation_pie(self, as_image=False, title=True):
        self.update_markets()
        allocation_df = self.index_df.copy()
        # allocation_df.loc[allocation_df['allocation'] < 0.03, 'symbol'] = 'Other'

        fig = px.pie(allocation_df, values='allocation', names='symbol',
                     color_discrete_sequence=px.colors.sequential.Viridis, hole=0.6)
        fig.update_traces(textposition='inside', textinfo='label', hoverinfo="label+percent")
        fig.update_layout(showlegend=False, title={'xanchor': 'center', 'x': 0.5},
                          uniformtext_minsize=min_font_size, uniformtext_mode='hide',
                          annotations=[
                              dict(text=f"{allocation_df['value'].sum():,.2f} {self.config.base_currency.values[1]}",
                                   x=0.5, y=0.5, font_size=text_size, showarrow=False)],
                          title_font=dict(size=title_size),
                          margin=dict(l=20, r=20, t=20, b=20))
        if title:
            fig.update_layout(title='Coin Allocation')
        if as_image:
            return fig.to_image(format='png', width=600, height=600)
        else:
            return fig

    def update_historical_prices(self, from_timestamp=None, force=False):
        if not force:
            # do not update, if last update less than 10 seconds ago
            if self.last_history_update > time()-60:
                print('stopped history update')
                return

        len_data = 0
        min_time = (self.trades_df['date'].min() - pd.DateOffset(2)).timestamp()
        if from_timestamp:
            start_date = from_timestamp if from_timestamp > min_time else min_time
        else:
            start_date = min_time
        end_date = time()
        for coin in self.index_df['symbol'].str.lower():
            id = self.markets.loc[self.markets['symbol'] == coin, ['id']].values[0][0]
            data = self.coingecko.get_coin_market_chart_range_by_id(id=id, vs_currency=self.config.base_currency.value,
                                                                    from_timestamp=start_date, to_timestamp=end_date)
            data_df = pd.DataFrame.from_records(data['prices'], columns=['timestamp', f'{coin}'])
            data_df['timestamp'] = pd.to_datetime(data_df['timestamp'], unit='ms', utc=True)
            data_df.set_index('timestamp', inplace=True)
            len_data = len(data_df) if len(data_df) > len_data else len_data
            if 'history_df' not in locals():
                history_df = data_df
            else:
                history_df = history_df.join(data_df, how='outer')

        n = 200 if len_data > 200 else len_data
        self.history_df = history_df.fillna(method='pad').fillna(method='bfill').reindex(pd.date_range(pd.to_datetime(start_date, unit='s', utc=True), pd.to_datetime(end_date, unit='s', utc=True), n), method='nearest')
        self.history_df.index = self.history_df.index.tz_convert('Europe/Berlin')
        self.last_history_update = time()

    def compute_value_history(self, from_timestamp=None):
        self.update_historical_prices(from_timestamp=from_timestamp)
        invested = self.trades_df[['date', 'buy_symbol', 'cost']].groupby(
            ['date', 'buy_symbol'], as_index=False, axis=0).sum()
        value = self.trades_df[['date', 'buy_symbol', 'amount']].groupby(
            ['date', 'buy_symbol'], as_index=False, axis=0).sum()
        invested = invested.pivot(index='date', columns='buy_symbol', values='cost')
        invested = invested.cumsum().fillna(method='pad').fillna(0)
        invested = invested.reindex(self.history_df.index, method='pad').fillna(0)
        invested.columns = invested.columns.str.lower()

        value = value.pivot(index='date', columns='buy_symbol', values='amount')
        value = value.cumsum().fillna(method='pad').fillna(0)
        value = value.reindex(self.history_df.index, method='pad').fillna(0)
        value.columns = value.columns.str.lower()
        value = value * self.history_df

        return value, invested

    def value_history_chart(self, as_image=False, from_timestamp=None, title=True):
        value, invested = self.compute_value_history(from_timestamp=from_timestamp)
        performance_df = pd.DataFrame(index=value.index, columns=['invested', 'net_worth'])
        performance_df['invested'] = invested.sum(axis=1)
        performance_df['net_worth'] = value.sum(axis=1)

        if performance_df['invested'].min() == performance_df['invested'].max():
            y = ['net_worth']
            color = [px.colors.sequential.Viridis[0]]
        else:
            y = ['invested', 'net_worth']
            color = ['gray', px.colors.sequential.Viridis[0]]

        fig = px.line(performance_df, x=performance_df.index, y=y, line_shape='spline', color_discrete_sequence=color)
        fig.update_xaxes(showgrid=False, title_text='')
        fig.update_yaxes(side='right', showgrid=True, ticksuffix=f' {self.config.base_currency.values[1]}',
                         title_text='', gridcolor='lightgray', gridwidth=0.15)
        fig.update_traces(selector=dict(name='invested'), line_shape='hv')
        fig.update_layout(showlegend=False, title={'xanchor': 'center', 'x': 0.5},
                          uniformtext_minsize=min_font_size, uniformtext_mode='hide', title_font=dict(size=title_size),
                          plot_bgcolor='white', margin=dict(l=20, r=20, t=20, b=20))
        if title:
            fig.update_layout(title='Portfolio value')
        if as_image:
            return fig.to_image(format='png', width=1200, height=600)
        else:
            return fig

    def performance_chart(self, as_image=False, from_timestamp=None, title=True):
        value, invested = self.compute_value_history(from_timestamp=from_timestamp)
        performance_df = pd.DataFrame(index=value.index, columns=['invested', 'net_worth'])
        performance_df['invested'] = invested.sum(axis=1)
        performance_df['net_worth'] = value.sum(axis=1)
        performance_df['performance'] = (performance_df['net_worth'] / performance_df['invested'] - 1) * 100

        fig = px.line(performance_df, x=performance_df.index, y='performance',
                      # line_shape='spline',
                      color_discrete_sequence=['green'])
        fig.update_xaxes(showgrid=False, title_text='')
        fig.update_yaxes(side='right', showgrid=True, ticksuffix=' %',
                         title_text='', gridcolor='lightgray', gridwidth=0.15)
        fig.update_layout(showlegend=False, title={'xanchor': 'center', 'x': 0.5},
                          uniformtext_minsize=min_font_size, uniformtext_mode='hide', title_font=dict(size=title_size),
                          plot_bgcolor='white', margin=dict(l=20, r=20, t=20, b=20))
        # fig.data = []
        # fig.add_scatter(x=performance_df.index, y=performance_df.performance.where(performance_df.performance >= 0),
        #                 fill='tozeroy',
        #                   line={'color': 'green',
        #                         # 'shape': 'spline'
        #                         })
        fig.add_scatter(x=performance_df.index, y=performance_df.performance.where(performance_df.performance < 0),
                        # fill='tozeroy',
                          line={'color': 'red',
                                # 'shape': 'spline'
                                })
        if title:
            fig.update_layout(title='Portfolio performance')
        if as_image:
            return fig.to_image(format='png', width=1200, height=600)
        else:
            return fig

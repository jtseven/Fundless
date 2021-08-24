import pandas as pd
from pathlib import Path

import requests.exceptions
from pycoingecko import CoinGeckoAPI
from pydantic import validate_arguments
from pydantic.types import constr
import plotly.express as px
from typing import Tuple
import numpy as np
from time import time
from redo import retrying
from threading import Lock

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
    history_df: pd.DataFrame = None
    coingecko: CoinGeckoAPI
    markets: pd.DataFrame  # CoinGecko Market Data

    last_market_update: float = 0  # seconds since epoch
    last_history_update_month: float = 0  # seconds since epoch
    last_history_update_day: float = 0
    history_update_lock = Lock()
    last_trades_update: float = 0

    def __init__(self, file_path, config: Config):
        self.config = config.trading_bot_config
        self.trades_file = Path(file_path)
        if self.trades_file.exists():
            self.update_trades_df()
        else:
            self.trades_df = pd.DataFrame(columns=trades_cols)
            self.trades_df.to_csv(self.trades_file, index=False)
            self.last_trades_update = time()
        self.coingecko = CoinGeckoAPI()
        self.update_markets()

    def update_trades_df(self):
        if self.last_trades_update < time() - 60:
            trades_df = pd.read_csv(self.trades_file, dtype=csv_dtypes, parse_dates=['date'])
            trades_df['date'] = trades_df['date'].dt.tz_localize('UTC')
            self.trades_df = trades_df
            self.last_trades_update = time()

    def update_file(self):
        self.trades_df.sort_values('date', inplace=True)
        self.trades_df.to_csv(self.trades_file, index=False)

    def update_markets(self, force=False):
        if not force:
            # do not update, if last update less than 10 seconds ago
            if self.last_market_update > time()-8:
                return

        # update market data from coingecko
        try:
            markets = pd.DataFrame.from_records(self.coingecko.get_coins_markets(
                vs_currency=self.config.base_currency.value, per_page=150))
            markets['symbol'] = markets['symbol'].str.lower()
        except Exception as e:
            print('Error while updating market data from CoinGecko:')
            print(e)
            raise e
        markets.replace(coingecko_symbol_dict, inplace=True)
        self.markets = markets
        self.last_market_update = time()

        # update index portfolio value
        other = pd.DataFrame(index=self.config.cherry_pick_symbols)
        index_df = self.trades_df[['buy_symbol', 'amount', 'cost']].copy().groupby('buy_symbol').sum()
        index_df.index = index_df.index.str.lower()
        index_df = pd.merge(index_df, other, how='outer', left_index=True, right_index=True)
        index_df.fillna(value=0, inplace=True, axis='columns')
        index_df = self.markets[['symbol', 'current_price']].join(index_df, on='symbol', how='inner')
        index_df['value'] = index_df['current_price'] * index_df['amount']
        index_df['allocation'] = index_df['value'] / index_df['value'].sum()
        index_df['symbol'] = index_df['symbol'].str.upper()
        index_df['performance'] = index_df['value'] / index_df['cost'] - 1
        self.index_df = index_df

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
        index = self.index_df.sort_values(by='allocation', ascending=False)
        allocations = index['allocation'].values * 100
        symbols = index['symbol'].values
        values = index['value'].values
        amounts = index['amount'].values
        return symbols, amounts, values, allocations

    def performance(self, current_portfolio_value: float) -> float:
        amount_invested = self.trades_df['cost'].sum()
        return current_portfolio_value / amount_invested - 1

    def invested(self) -> float:
        return self.trades_df['cost'].sum()

    def allocation_pie(self, as_image=False, title=True):
        try:
            self.update_markets()
        except requests.exceptions.HTTPError:
            pass
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

    def update_historical_prices(self):
        to_timestamp = time()
        freq = None
        month = 60*60*24*30
        day = 60*60*24
        if self.history_df is None:
            # get full history from api
            min_time = (self.trades_df['date'].min() - pd.DateOffset(2)).timestamp()
            from_timestamp = min_time
        elif self.last_history_update_month < time() - 60*60*24*2:  # t - 2days
            # get data from last month
            from_timestamp = time() - month
            freq = 'H'
            self.last_history_update_month = time()
        elif self.last_history_update_day < time() - 60*15:  # t - 15min
            from_timestamp = time() - day
            self.last_history_update_day = time()
            freq = '5T'  # 5 minutes
        else:
            # no update needed
            return

        with self.history_update_lock:
            # pull historic market data for all coins (pretty heavy on API requests)
            for coin in self.index_df['symbol'].str.lower():
                id = self.markets.loc[self.markets['symbol'] == coin, ['id']].values[0][0]
                with retrying(self.coingecko.get_coin_market_chart_range_by_id, sleeptime=0.5, sleepscale=1, jitter=0,
                              retry_exceptions=requests.exceptions.HTTPError) as get_history:
                    data = get_history(id=id, vs_currency=self.config.base_currency.value,
                                       from_timestamp=from_timestamp, to_timestamp=to_timestamp)
                data_df = pd.DataFrame.from_records(data['prices'], columns=['timestamp', f'{coin}'])
                data_df['timestamp'] = pd.to_datetime(data_df['timestamp'], unit='ms', utc=True)
                data_df.set_index('timestamp', inplace=True)
                if 'history_df' not in locals():
                    history_df = data_df
                else:
                    history_df = history_df.join(data_df, how='outer')

            if freq is not None:
                # round datetime index to given frequency,
                # otherwise all coins have price data at slightly different times
                history_df = history_df.fillna(method='pad').fillna(method='bfill').reindex(history_df.index.round(freq).drop_duplicates(), method='nearest')
                if freq == 'H':
                    truncate_from = pd.to_datetime(from_timestamp, unit='s', utc=True)
                    truncate_to = pd.to_datetime(to_timestamp-day, unit='s', utc=True)
                elif freq == '5T':
                    truncate_from = pd.to_datetime(to_timestamp-day, unit='s', utc=True)
                    truncate_to = pd.to_datetime(time(), unit='s', utc=True)
            else:
                truncate_from = pd.to_datetime(time(), unit='s', utc=True)
                truncate_to = truncate_from

            # add most recent prices for data consistency
            current_prices = [self.markets.loc[self.markets['symbol'] == symbol, ['current_price']].values[0][0] for symbol in list(history_df.columns)]
            history_df = history_df.append(pd.DataFrame([current_prices], columns=history_df.columns, index=[
                pd.to_datetime(int(time()), unit='s', utc=True)])).sort_index()

            # convert to local timezone
            history_df.index = history_df.index.tz_convert('Europe/Berlin')

            if self.history_df is not None:
                mask = (self.history_df.index < truncate_from) | (self.history_df.index > truncate_to)
                history_df = pd.concat([history_df, self.history_df.loc[mask]])
                history_df = history_df[~history_df.index.duplicated(keep='first')].sort_index()
            self.history_df = history_df

    def compute_value_history(self, from_timestamp=None):
        if self.history_df is None:
            self.update_historical_prices()

        if from_timestamp is not None:
            start_time = pd.to_datetime(from_timestamp, unit='s', utc=True)
            price_history = self.history_df.copy().truncate(before=start_time)
        else:
            price_history = self.history_df.copy()
            start_time = price_history.index.min()
        if start_time < (pd.to_datetime(int(time()), unit='s', utc=True) - pd.DateOffset(days=31)):
            freq = 'D'
        elif start_time < (pd.to_datetime(int(time()), unit='s', utc=True) - pd.DateOffset(days=14, minutes=2)):
            freq = '3H'
        elif start_time < (pd.to_datetime(int(time()), unit='s', utc=True) - pd.DateOffset(days=1, minutes=2)):
            freq = 'H'
        else:
            freq = '5T'  # 5 minutes

        price_history = price_history.asfreq(freq=freq, method='pad')
        # add most recent prices for data consistency
        current_prices = [self.markets.loc[self.markets['symbol'] == symbol, ['current_price']].values[0][0] for symbol
                          in list(price_history.columns)]
        price_history = price_history.append(pd.DataFrame([current_prices], columns=price_history.columns, index=[
            pd.to_datetime(int(time()), unit='s', utc=True).tz_convert('Europe/Berlin')])).sort_index()
        if start_time+pd.Timedelta(days=2) < price_history.index.min():
            price_history = price_history.append(pd.DataFrame(0, index=[start_time], columns=price_history.columns)).sort_index()

        invested = self.trades_df[['date', 'buy_symbol', 'cost']].groupby(
            ['date', 'buy_symbol'], as_index=False, axis=0).sum()
        value = self.trades_df[['date', 'buy_symbol', 'amount']].groupby(
            ['date', 'buy_symbol'], as_index=False, axis=0).sum()
        invested = invested.pivot(index='date', columns='buy_symbol', values='cost')
        invested = invested.cumsum().fillna(method='pad').fillna(0)
        invested = invested.reindex(price_history.index, method='pad').fillna(0)
        invested.columns = invested.columns.str.lower()

        value = value.pivot(index='date', columns='buy_symbol', values='amount')
        value = value.cumsum().fillna(method='pad').fillna(0)
        value = value.reindex(price_history.index, method='pad').fillna(0)
        value.columns = value.columns.str.lower()
        value = value * price_history

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
        fig.update_xaxes(showgrid=False, title_text='', fixedrange=True)
        fig.update_yaxes(side='right', showgrid=True, ticksuffix=f' {self.config.base_currency.values[1]}',
                         title_text='', gridcolor='lightgray', gridwidth=0.15, fixedrange=True)
        fig.update_traces(selector=dict(name='invested'), line_shape='hv')
        fig.update_layout(showlegend=False, title={'xanchor': 'center', 'x': 0.5},
                          uniformtext_minsize=min_font_size, uniformtext_mode='hide', title_font=dict(size=title_size),
                          plot_bgcolor='white', margin=dict(l=10, r=10, t=10, b=10))
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
        performance_df['invested'] += performance_df['net_worth'].iloc[0] - performance_df['invested'].iloc[0]
        performance_df['performance'] = (performance_df['net_worth'] / performance_df['invested'] - 1) * 100
        performance_df.fillna(0, inplace=True)

        fig = px.line(performance_df, x=performance_df.index, y='performance',
                      line_shape='spline',
                      color_discrete_sequence=['green'])
        fig.update_xaxes(showgrid=False, title_text='', zeroline=True, fixedrange=True)
        fig.update_yaxes(side='right', showgrid=False, ticksuffix=' %', zeroline=True, zerolinecolor='lightgray',
                         title_text='', zerolinewidth=0.2, fixedrange=True)
        fig.update_layout(showlegend=False, title={'xanchor': 'center', 'x': 0.5},
                          uniformtext_minsize=min_font_size, uniformtext_mode='hide', title_font=dict(size=title_size),
                          plot_bgcolor='white', margin=dict(l=10, r=10, t=10, b=10))
        fig.add_scatter(x=performance_df.index, y=performance_df.performance.where(performance_df.performance < 0),
                          line={'color': 'red',
                                'shape': 'spline'
                                })
        if title:
            fig.update_layout(title='Portfolio performance')
        if as_image:
            return fig.to_image(format='png', width=1200, height=600)
        else:
            return fig

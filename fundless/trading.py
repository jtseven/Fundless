import ccxt
import numpy as np
import pandas as pd
from pycoingecko import CoinGeckoAPI
from typing import List, Tuple
from datetime import datetime

from config import Config, TradingBotConfig, SecretsStore, ExchangeEnum, WeightingEnum, OrderTypeEnum
from analytics import PortfolioAnalytics


def print_order_allocation(symbols: np.ndarray, weights:np.ndarray):
    print(f" ------ Order Allocation: ------ ")
    for symbol, weight in zip(symbols, weights):
        ticker = f'{symbol.upper()}'
        print(f"\t- {ticker}:\t{(weight*100):5.2f} %")


class TradingBot:
    bot_config: TradingBotConfig
    analytics: PortfolioAnalytics
    secrets: SecretsStore
    exchange: ccxt.Exchange
    usd_symbols = ['USD', 'USDT', 'BUSD', 'USDC']

    def __init__(self, bot_config: Config, analytics: PortfolioAnalytics):
        self.bot_config = bot_config.trading_bot_config
        self.secrets = bot_config.secrets
        self.analytics = analytics
        self.init_exchange()

    def init_exchange(self):
        if self.bot_config.exchange == ExchangeEnum.binance:
            self.exchange = ccxt.binance()
            if self.bot_config.test_mode:
                self.exchange.apiKey = self.secrets.binance_test['api_key']
                self.exchange.secret = self.secrets.binance_test['secret']
            else:
                self.exchange.apiKey = self.secrets.binance['api_key']
                self.exchange.secret = self.secrets.binance['secret']
        elif self.bot_config.exchange == ExchangeEnum.kraken:
            self.exchange = ccxt.kraken()
            if self.bot_config.test_mode:
                self.exchange.apiKey = self.secrets.kraken_test['api_key']
                self.exchange.secret = self.secrets.kraken_test['secret']
            else:
                self.exchange.apiKey = self.secrets.kraken['api_key']
                self.exchange.secret = self.secrets.kraken['secret']
        else:
            raise ValueError('Invalid Exchange given!')

        self.exchange.set_sandbox_mode(self.bot_config.test_mode)
        self.exchange.load_markets()

    def balance(self) -> Tuple:
        try:
            data = self.exchange.fetch_total_balance()
            markets = self.exchange.fetch_tickers()
        except Exception as e:
            print(f"Error while getting balance from exchange:")
            print(e)
            raise e
        symbols = np.fromiter([key for key in data.keys() if data[key] > 0.0], dtype='U10')
        amounts = np.fromiter([data.get(symbol, 0.0) for symbol in symbols], dtype=float)
        base = self.bot_config.base_symbol.upper()
        try:
            values = np.array([float(
                markets[f'{key.upper()}/{base}']['last']) * amount if key.upper() not in self.usd_symbols else amount
                               for key, amount in zip(symbols, amounts)])
        except KeyError as e:
            print(f"Error: The symbol {e.args[0]} is not in the {self.bot_config.exchange.value} market data!")
            raise
        allocations = values/values.sum()*100
        sorted = values.argsort()
        symbols = symbols[sorted[::-1]]
        amounts = amounts[sorted[::-1]]
        values = values[sorted[::-1]]
        allocations = allocations[sorted[::-1]]

        return symbols, amounts, values, allocations

    def allocation_error(self, order_volume: float = None) -> dict:
        allocation_error = {}

        symbols, amounts, values, allocations = self.analytics.index_balance()
        allocations = allocations
        _, index_weights = self.fetch_index_weights(symbols)
        allocation_error['symbols'] = symbols
        allocation_error['relative'] = np.divide(allocations/100, index_weights)
        allocation_error['percentage_points'] = allocations - (index_weights * 100)
        allocation_error['absolute'] = values - index_weights * values.sum()
        allocation_error['index_weights'] = index_weights

        volume = order_volume or self.bot_config.savings_plan_cost
        allocation_error['rel_to_order_volume'] = \
            np.divide(np.abs(allocation_error['absolute']), volume)

        return allocation_error

    def rebalancing_weights(self, order_volume: float = None) -> Tuple[np.ndarray, np.ndarray]:
        volume = order_volume or self.bot_config.savings_plan_cost
        allocation_error = self.allocation_error()
        index_weights = allocation_error['index_weights']
        absolute_error = allocation_error['absolute']
        volumes = volume * index_weights - absolute_error
        volumes = volumes.clip(min=0)
        rebalancing_volume = volumes.sum()
        if rebalancing_volume < volume:
            volumes = volumes + (volume-rebalancing_volume) * index_weights
        weights = volumes / volumes.sum()
        return allocation_error['symbols'], weights

    def volume_corrected_weights(self, symbols: np.ndarray, weights: np.ndarray, order_volume: float = None):
        volume = order_volume or self.bot_config.savings_plan_cost
        volume_fail = self.check_order_limits(symbols, weights, volume, fail_fast=True)
        if len(volume_fail) > 0:
            sorter = weights.argsort()
            sorted_weights = weights[sorter[1:]]
            sorted_symbols = symbols[sorter[1:]]
            for i, _ in enumerate(sorted_symbols):
                check_symbols = sorted_symbols[i:].copy()
                check_weights = sorted_weights[i:].copy()
                check_weights = check_weights/check_weights.sum()
                check = self.check_order_limits(check_symbols, check_weights, volume, fail_fast=True)
                if len(check) == 0:
                    return check_symbols, check_weights
            raise ValueError('Order is not executable, overall volume too low!')
        return symbols, weights

    # Compute the weights by market cap, fetching data from coingecko
    # Square root weights yield a less top heavy distribution of coin allocation (lower bitcoin weighting)
    def fetch_index_weights(self, symbols: np.ndarray = None):
        self.analytics.update_markets()
        if symbols is not None:
            symbols = [symbol.lower() for symbol in symbols]
            picked_markets = self.analytics.markets.loc[self.analytics.markets['symbol'].isin(symbols)]
            # sort df equal to symbols array
            sorter_index = dict(zip(symbols, range(len(symbols))))
            picked_markets['rank'] = picked_markets['symbol'].map(sorter_index)
            picked_markets.sort_values('rank', ascending=True, inplace=True)
        else:
            picked_markets = self.analytics.markets.loc[self.analytics.markets['symbol'].isin(self.bot_config.cherry_pick_symbols)]
            symbols = picked_markets['symbol'].values
            if len(picked_markets) < len(self.bot_config.cherry_pick_symbols):
                print("Warning: Market data for some coins was not available on CoinGecko, they are not included in the index:")
                for coin in self.bot_config.cherry_pick_symbols:
                    if coin not in symbols:
                        print(f"\t{coin.upper()}")

        if self.bot_config.portfolio_weighting == WeightingEnum.equal:
            weights = np.full(len(symbols), float(1/len(symbols)))
        elif self.bot_config.portfolio_weighting == WeightingEnum.custom:
            weights = np.zeros(len(symbols))
            for k, symbol in enumerate(symbols):
                if symbol in self.bot_config.custom_weights:
                    weights[k] = self.bot_config.custom_weights[symbol]
            weights = weights / weights.sum()
        else:
            weights = picked_markets['market_cap'].values
            if self.bot_config.portfolio_weighting == WeightingEnum.sqrt_market_cap:
                weights = np.sqrt(weights)
            elif self.bot_config.portfolio_weighting == WeightingEnum.sqrt_sqrt_market_cap:
                weights = np.sqrt(np.sqrt(weights))
            elif self.bot_config.portfolio_weighting == WeightingEnum.cbrt_market_cap:
                weights = np.cbrt(weights)
            weights = weights / weights.sum()
        return symbols, weights

    def check_order_executable(self, symbols: np.ndarray, weights: np.ndarray, volume_usd: float):
        # Pull latest market data
        self.exchange.fetch_markets()
        # Check for any complications
        problems = {'symbols': {}, 'fail': False, 'occurred': False, 'description': '', 'skip_coins': []}
        for symbol, weight in zip(symbols, weights):
            ticker = f'{symbol.upper()}/{self.bot_config.base_symbol.upper()}'
            if ticker not in self.exchange.symbols:
                print(f"Warning: {ticker} not available, skipping...")
                problems['occurred'] = True
                problems['fail'] = True
                problems['description'] = f'Symbol {ticker} not available'
                problems['symbols'][symbol] = 'not available'
        if problems['occurred']:
            return problems

        volume_fail = self.check_order_limits(symbols, weights, volume_usd)
        if len(volume_fail) > 0:
            for symbol in volume_fail:
                print(f"The order amount of {symbol.upper()} is to low! Skipping...")
                problems['occurred'] = True
                problems['description'] = f'Order amount for {symbol.upper()} too low'
                problems['symbols'][symbol] = 'amount too low'
                problems['skip_coins'].append(symbol)
        balance = self.exchange.fetch_balance()
        if balance['free'][self.bot_config.base_symbol.upper()] is not None:
            balance = balance['free'][self.bot_config.base_symbol.upper()]
        else:
            balance = balance['total'][self.bot_config.base_symbol.upper()]
        if balance < self.bot_config.savings_plan_cost:
            print(
                f"Warning: Insufficient funds to execute savings plan! Your have {balance:.2f} {self.bot_config.base_symbol.upper()}")
            problems['occurred'] = True
            problems['fail'] = True
            problems['description'] = \
                f'Insufficient funds to execute savings plan, you have {balance:.2f} {self.bot_config.base_symbol.upper()}'
        return problems

    def check_order_limits(self, symbols: np.ndarray, weights: np.ndarray, volume_usd: float, fail_fast=False):
        volume_fail = []
        for symbol, weight in zip(symbols, weights):
            ticker = f'{symbol.upper()}/{self.bot_config.base_symbol.upper()}'
            price = self.exchange.fetch_ticker(ticker).get('last')
            cost = weight * volume_usd
            amount = weight * volume_usd / price

            if amount <= self.exchange.markets[ticker]['limits']['amount']['min']:
                volume_fail.append(symbol)
                if fail_fast:
                    return volume_fail
            elif cost <= self.exchange.markets[ticker]['limits']['cost']['min']:
                volume_fail.append(symbol)
                if fail_fast:
                    return volume_fail

        return volume_fail

    # Place a weighted market buy order on Binance for multiple coins
    def weighted_buy_order(self, symbols: np.ndarray, weights: np.ndarray, volume_usd: float = None,
                           order_type: OrderTypeEnum = OrderTypeEnum.market) -> dict:
        volume = volume_usd or self.bot_config.savings_plan_cost  # order volume denoted in base currency
        print_order_allocation(symbols, weights)
        self.exchange.load_markets()
        report = {'problems': self.check_order_executable(symbols, weights, volume), 'order_ids': []}
        if report['problems']['fail']:
            return report

        placed_volume = 0
        invalid = []
        placed_ids = []
        placed_symbols = []

        # Start buying
        before = self.exchange.fetch_total_balance()
        for symbol, weight in zip(symbols, weights):
            ticker = f'{symbol.upper()}/{self.bot_config.base_symbol.upper()}'
            price = self.exchange.fetch_ticker(ticker).get('last')
            limit_price = 0.998*price
            cost = weight * volume
            amount = weight * volume / price
            try:
                if order_type == OrderTypeEnum.limit:
                    order = self.exchange.create_limit_buy_order(ticker, amount, price=limit_price)
                elif order_type == OrderTypeEnum.market:
                    order = self.exchange.create_market_buy_order(ticker, amount)
                else:
                    raise ValueError(f"Invalid order type: {order_type}")
            except ccxt.InvalidOrder as e:
                print(f"Buy order for {amount} {ticker} is invalid!")
                print(e)
                invalid.append(symbol)
                continue
            except ccxt.BaseError as e:
                print(f"Error during order for {amount} {ticker}!")
                print(e)
                continue
            else:
                print(f"Placed order for {order['amount']:5f} {ticker} at {order['price']:.2f} $")
                placed_symbols.append(ticker)
                placed_ids.append(order['id'])

        report['order_ids'] = placed_ids
        report['symbols'] = placed_symbols
        report['invalid_symbols'] = invalid
        # Report state of portfolio before and after buy orders
        after = self.exchange.fetch_total_balance()
        return report

    def check_orders(self, order_ids: List, symbols: List) -> dict:
        closed_orders = []
        open_orders = []
        order_report = {symbol: {} for symbol in symbols}
        for id, symbol in zip(order_ids, symbols):
            order = self.exchange.fetch_order(id, symbol)
            if order['status'] == 'closed':
                order_report[symbol]['status'] = 'closed'
                order_report[symbol]['price'] = order['price']
                order_report[symbol]['cost'] = order['cost']
                closed_orders.append(symbol)
                self.analytics.add_trade(date=datetime.fromtimestamp(order['timestamp']/1000.0).strftime('%Y-%m-%d %H:%M:%S'),
                                         buy_symbol=order['symbol'].split('/')[0],
                                         sell_symbol=order['symbol'].split('/')[1],
                                         price=order['price'],
                                         amount=order['amount'],
                                         cost=order['cost'],
                                         fee=order['fee'] or 0.0,
                                         fee_symbol='')
            elif order['status'] == 'open':
                order_report['symbol'] = 'open'
                open_orders.append(symbol)
            else:
                print('Your order is neither open, nor closed... something went wrong!')
        order_report['closed'] = closed_orders
        order_report['open'] = open_orders
        return order_report

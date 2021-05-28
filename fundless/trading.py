import ccxt
import numpy as np
import pandas as pd
from pycoingecko import CoinGeckoAPI
from typing import List

from config import Config, TradingBotConfig, SecretsStore, ExchangeEnum, WeightingEnum, OrderTypeEnum

# translate coingecko symbols to ccxt/binance symbols
coingecko_symbol_dict = {
    'miota': 'iota'
}


def print_order_allocation(symbols: np.ndarray, weights:np.ndarray):
    print(f" ------ Order Allocation: ------ ")
    for symbol, weight in zip(symbols, weights):
        ticker = f'{symbol.upper()}'
        print(f"\t- {ticker}:\t{(weight*100):5.2f} %")


class TradingBot:
    bot_config: TradingBotConfig
    secrets: SecretsStore
    exchange: ccxt.Exchange
    coingecko: CoinGeckoAPI
    markets: pd.DataFrame  # CoinGecko Market Data
    usd_symbols = ['USD', 'USDT', 'BUSD', 'USDC']

    def __init__(self, bot_config: Config):
        self.bot_config = bot_config.trading_bot_config
        self.secrets = bot_config.secrets
        self.init_exchange()
        self.coingecko = CoinGeckoAPI()
        self.update_markets()


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
            raise NotImplementedError("Kraken is not yet supported!")
        else:
            raise ValueError('Invalid Exchange given!')

        self.exchange.set_sandbox_mode(self.bot_config.test_mode)
        self.exchange.load_markets()

    @property
    def balance(self) -> tuple:
        try:
            data = self.exchange.fetch_total_balance()
            markets = self.exchange.fetch_tickers()
        except Exception as e:
            print(f"Error while getting balance from exchange:")
            print(e)
            raise e
        symbols = np.fromiter([key for key in data.keys() if data[key] > 0.0], dtype='U10')
        amounts = np.fromiter([data[symbol] for symbol in symbols], dtype=float)
        base = self.bot_config.base_symbol.upper()
        try:
            values = np.array([float(markets[f'{key.upper()}/{base}']['last'])*amount if key.upper() not in self.usd_symbols else amount for key, amount in zip(symbols, amounts)])
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

    @property
    def index_balance(self) -> dict:
        try:
            data = self.exchange.fetch_total_balance()
            markets = self.exchange.fetch_tickers()
        except Exception as e:
            print(f"Error while getting balance from exchange:")
            print(e)
            raise e
        symbols = np.fromiter([key for key in data.keys() if data[key] > 0.0 and key.lower() in self.bot_config.cherry_pick_symbols], dtype='U10')
        amounts = np.fromiter([data[symbol] for symbol in symbols], dtype=float)
        base = self.bot_config.base_symbol.upper()
        try:
            values = np.array(
                [float(markets[f'{key.upper()}/{base}']['last']) * amount if key.upper() != base else amount for
                 key, amount in zip(symbols, amounts)])
        except KeyError as e:
            print(f"Error: The symbol {e.args[0]} is not in the {self.bot_config.exchange.value} market data!")
            raise
        allocations = values / values.sum() * 100
        sorted = values.argsort()
        symbols = symbols[sorted[::-1]]
        amounts = amounts[sorted[::-1]]
        values = values[sorted[::-1]]
        allocations = allocations[sorted[::-1]]

        return symbols, amounts, values, allocations

    def update_markets(self):
        try:
            self.markets = pd.DataFrame.from_records(self.coingecko.get_coins_markets(
                vs_currency=self.bot_config.base_currency.value))
            self.markets['symbol'] = self.markets['symbol'].str.lower()
        except Exception as e:
            print('Error while updating market data from CoinGecko:')
            print(e)
            raise e
        self.markets.replace(coingecko_symbol_dict, inplace=True)

    # Compute the weights by market cap, fetching data from coingecko
    # Square root weights yield a less top heavy distribution of coin allocation (lower bitcoin weighting)
    def fetch_index_weights(self, symbols: np.ndarray = None):
        self.update_markets()
        picked_markets = self.markets.loc[self.markets['symbol'].isin(self.bot_config.cherry_pick_symbols)]
        symbols = symbols if symbols is not None else picked_markets['symbol'].values
        if len(picked_markets) < len(self.bot_config.cherry_pick_symbols):
            print("Warning: Market data for some coins was not available on CoinGecko, they are not included in the index:")
            for coin in self.bot_config.cherry_pick_symbols:
                if coin not in symbols:
                    print(f"\t{coin.upper()}")
        if self.bot_config.portfolio_weighting == WeightingEnum.equal:
            weights = np.full(len(symbols), float(1/len(symbols)))
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
        problems = {'symbols': {}, 'occurred': False, 'description': ''}
        for symbol, weight in zip(symbols, weights):
            ticker = f'{symbol.upper()}/{self.bot_config.base_symbol.upper()}'
            if ticker not in self.exchange.symbols:
                print(f"Warning: {ticker} not available, skipping...")
                problems['occurred'] = True
                problems['description'] = f'Symbol {ticker} not available'
                problems['symbols'][ticker] = 'not available'
            else:
                price = self.exchange.fetch_ticker(ticker).get('last')
                if price <= 0.0:
                    print(f"Warning: Price for {ticker} is {price}, skipping {ticker}...")
                    problems['occurred'] = True
                    problems['description'] = f'Price for {ticker} zero or below'
                    problems['symbols'][ticker] = 'price <= zero'
                    continue
                cost = weight * volume_usd
                amount = weight * volume_usd / price
                if amount <= self.exchange.markets[ticker]['limits']['amount']['min']:
                    print(f"The order amount of {ticker} is to low! Skipping...")
                    problems['occurred'] = True
                    problems['description'] = f'Order amount for {ticker} too low'
                    problems['symbols'][ticker] = 'amount too low'
                if cost <= self.exchange.markets[ticker]['limits']['cost']['min']:
                    print(f"The order cost of {cost} $ is to low for {ticker}! Skipping...")
                    problems['occurred'] = True
                    problems['description'] = f'Order cost for {ticker} too low'
                    problems['symbols'][ticker] = 'cost too low'
        balance = self.exchange.fetch_free_balance()[self.bot_config.base_symbol.upper()]
        if balance < self.bot_config.savings_plan_cost:
            print(
                f"Warning: Insufficient funds to execute savings plan! Your have {balance:.2f} {self.bot_config.base_symbol.upper()}")
            problems['occurred'] = True
            problems['description'] = \
                f'Insufficient funds to execute savings plan, you have {balance:.2f} {self.bot_config.base_symbol.upper()}'
        return problems

    # Place a weighted market buy order on Binance for multiple coins
    def weighted_buy_order(self, symbols: np.ndarray, weights: np.ndarray, volume_usd: float = None,
                           order_type: OrderTypeEnum = OrderTypeEnum.market) -> dict:
        volume = volume_usd or self.bot_config.savings_plan_cost  # order volume denoted in base currency
        print_order_allocation(symbols, weights)
        self.exchange.load_markets()
        report = {'problems': self.check_order_executable(symbols, weights, volume), 'order_ids': []}
        if report['problems']['occurred']:
            return report

        placed_volume = 0
        invalid = []
        placed_ids = []
        placed_symbols = []

        # Start buying
        before = self.exchange.fetch_free_balance()
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

            # order = self.exchange.fetch_order(order['id'], symbol=ticker)
            # if order['status'] != 'closed':
            #     print(f"Warning: Order for {ticker} has status {order['status']}... skipping!")
            #     continue
            # else:
            # print(f"Bought {order['amount']:5f} {ticker} at {order['price']:.2f} $")
        report['order_ids'] = placed_ids
        report['symbols'] = placed_symbols
        report['invalid_symbols'] = invalid
        # Report state of portfolio before and after buy orders
        after = self.exchange.fetch_free_balance()
        print("Balances before order execution:")
        print(before)
        print("Balances after order execution:")
        print(after)
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
            elif order['status'] == 'open':
                order_report['symbol'] = 'open'
                open_orders.append(symbol)
            else:
                print('Your order is neither open, nor closed... something went wrong!')
        order_report['closed'] = closed_orders
        order_report['open'] = open_orders
        return order_report

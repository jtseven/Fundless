import ccxt
import numpy as np
from typing import List, Tuple, Union
from datetime import datetime
from redo import retrying
import logging

from config import Config, SecretsStore, ExchangeEnum, WeightingEnum, OrderTypeEnum
from analytics import PortfolioAnalytics
from utils import print_crypto_amount
import logging
from constants import USD_SYMBOLS, FIAT_SYMBOLS
from exchanges import Exchanges


logger = logging.getLogger(__name__)


def print_order_allocation(symbols: np.ndarray, weights:np.ndarray):
    logger.info(f" ------ Order Allocation: ------ ")
    for symbol, weight in zip(symbols, weights):
        ticker = f'{symbol.upper()}'
        logger.info(f"\t- {ticker}:\t{(weight*100):5.2f} %")


class TradingBot:
    bot_config: Config
    analytics: PortfolioAnalytics
    secrets: SecretsStore
    exchange: ccxt.Exchange

    def __init__(self, bot_config: Config, analytics: PortfolioAnalytics, exchanges: Exchanges):
        self.bot_config = bot_config
        self.secrets = bot_config.secrets
        self.analytics = analytics
        self.exchanges = exchanges

        not_available = [symbol.upper() for symbol in self.bot_config.trading_bot_config.cherry_pick_symbols if
                         f'{symbol.upper()}/{self.bot_config.trading_bot_config.base_symbol.upper()}' not in
                         self.exchanges.active.symbols and symbol != self.bot_config.trading_bot_config.base_symbol]
        if len(not_available) > 0:
            logger.warning(f'Some of your cherry picked coins are not available on {self.exchanges.active.name}:')
            logger.warning(not_available)

    def balance(self) -> Tuple:
        # TODO fix for different base symbol and base currency and use analytics module
        try:
            data = self.exchanges.active.fetch_total_balance()

            # if self.exchanges.active.has['fetchTickers']:
            #     markets = self.exchanges.active.fetch_tickers()
            # else:
            #     markets = None
            #     # # TODO pull market data in an alternative way
            #     # raise NotImplementedError("Exchange does not support fetching tickers!")
        except Exception as e:
            logger.error(f"Error while getting balance from exchange:")
            logger.error(e)
            raise e
        symbols = np.fromiter([key for key in data.keys() if data[key] > 0.0], dtype='U10')
        amounts = np.fromiter([data.get(symbol, 0.0) for symbol in symbols], dtype=float)
        # base = self.bot_config.trading_bot_config.base_symbol.upper()
        # if markets is not None:
        #     # use exchange market data
        #     try:
        #         values = np.array([float(
        #             markets[f'{key.upper()}/{base}']['last']) * amount if key.upper() not in FIAT_SYMBOLS
        #                                                                   and key.upper != base else
        #                            self.analytics.convert(amount, key, base)
        #                            for key, amount in zip(symbols, amounts)])
        #     except KeyError as e:
        #         print(
        #             f"Error: The symbol {e.args[0]} is not in the {self.bot_config.trading_bot_config.exchange.value} market data!")
        #         raise
        # else:
        #     # use coingecko market data from analytics module
        #     values = np.array([float(
        #         self.analytics.markets.loc[self.analytics.markets['symbol'] == symbol, ['current_price']].values[0][0]
        #     ) for symbol in symbols])
        base_currency = self.bot_config.trading_bot_config.base_currency
        values = np.asarray([self.analytics.convert(amount, symbol, base_currency)
                             for amount, symbol in zip(amounts, symbols)])
        # TODO: Take exchange prices if possible

        allocations = values/values.sum()*100
        sorted = values.argsort()
        symbols = symbols[sorted[::-1]]
        amounts = amounts[sorted[::-1]]
        values = values[sorted[::-1]]
        allocations = allocations[sorted[::-1]]

        return symbols, amounts, values, allocations

    def allocation_error(self, base_currency_volume: float = None) -> dict:
        allocation_error = {}

        symbols, amounts, values, allocations = self.analytics.index_balance()
        allocations = allocations
        symbols, index_weights = self.analytics.fetch_index_weights(symbols)
        allocation_error['symbols'] = symbols
        allocation_error['relative'] = np.divide(allocations/100, index_weights)
        allocation_error['percentage_points'] = allocations - (index_weights * 100)
        allocation_error['absolute'] = values - index_weights * values.sum()
        allocation_error['index_weights'] = index_weights

        volume = base_currency_volume or self.bot_config.trading_bot_config.savings_plan_cost
        allocation_error['rel_to_order_volume'] = \
            np.divide(np.abs(allocation_error['absolute']), volume)

        return allocation_error

    def rebalancing_weights(self, base_currency_volume: float = None) -> Tuple[np.ndarray, np.ndarray]:
        volume = base_currency_volume or self.bot_config.trading_bot_config.savings_plan_cost
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

    def volume_corrected_weights(self, symbols: np.ndarray, weights: np.ndarray, base_currency_volume: float = None):
        symbols = np.asarray(symbols)
        weights = np.asarray(weights)
        volume = base_currency_volume or self.bot_config.trading_bot_config.savings_plan_cost
        volume = self.analytics.base_currency_to_base_symbol(volume)
        weights = weights/weights.sum()

        volume_fail, reason = self.check_order_limits(symbols, weights, volume, fail_fast=True)
        if len(volume_fail) > 0:
            sorter = weights.argsort()
            sorted_weights = weights[sorter[1:]]
            sorted_symbols = symbols[sorter[1:]]
            for i, _ in enumerate(sorted_symbols):
                check_symbols = sorted_symbols[i:].copy()
                check_weights = sorted_weights[i:].copy()
                check_weights = check_weights/check_weights.sum()
                check, reason = self.check_order_limits(check_symbols, check_weights, volume, fail_fast=True)
                if len(check) == 0:
                    # sort by weight again
                    sorter = check_weights.argsort()
                    return check_symbols[sorter[::-1]], check_weights[::-1], None
            return [], [], reason  # the volume is too low even when buying just one coin -> no order executable
        return symbols, weights, []

    def check_order_executable(self, symbols: np.ndarray, weights: np.ndarray, base_symbol_volume: float):
        # Pull latest market data
        self.exchanges.active.fetch_markets()
        # Check for any complications
        problems = {'symbols': {}, 'fail': False, 'occurred': False, 'description': '', 'skip_coins': []}
        for symbol, weight in zip(symbols, weights):
            if symbol.lower() == self.bot_config.trading_bot_config.base_symbol.lower():
                continue
            ticker = f'{symbol.upper()}/{self.bot_config.trading_bot_config.base_symbol.upper()}'
            if ticker not in self.exchanges.active.symbols:
                logger.warning(f"Warning: {ticker} not available, skipping...")
                problems['occurred'] = True
                problems['fail'] = True
                problems['description'] = f'Symbol {ticker} not available'
                problems['symbols'][symbol] = 'not available'
        if problems['occurred']:
            return problems

        volume_fail, reasons = self.check_order_limits(symbols, weights, base_symbol_volume)
        if len(volume_fail) > 0:
            for symbol, reason in zip(volume_fail, reasons):
                logger.warning(f"Order of {symbol.upper()} not possible: {reason}. Skipping...")
                problems['occurred'] = True
                problems['description'] = f'{symbol.upper()}: {reason}'
                problems['symbols'][symbol] = reason
                problems['skip_coins'].append(symbol)
        balance = self.exchanges.active.fetch_balance()
        if balance['free'][self.bot_config.trading_bot_config.base_symbol.upper()] is not None:
            balance = balance['free'][self.bot_config.trading_bot_config.base_symbol.upper()]
        else:
            balance = balance['total'][self.bot_config.trading_bot_config.base_symbol.upper()]
        insufficient = False
        if balance < base_symbol_volume:
            insufficient = True
            base_symbol = self.bot_config.trading_bot_config.base_symbol.upper()
            if base_symbol.upper() in FIAT_SYMBOLS:
                print_balance = f'{balance:.2f}'
                print_volume = f'{base_symbol_volume:.2f}'
            else:
                print_balance = print_crypto_amount(balance)
                print_volume = print_crypto_amount(base_symbol_volume)

            problems['description'] = \
                f'Insufficient funds to execute savings plan, you have {print_balance} {base_symbol}' + \
                f'\nYou need {print_volume} {self.bot_config.trading_bot_config.base_symbol.upper()}'
        if self.bot_config.trading_bot_config.base_symbol.upper() in symbols:
            index_symbols, index_amounts, _, _ = self.analytics.index_balance()
            index = index_symbols.tolist().index(self.bot_config.trading_bot_config.base_symbol.upper())
            base_symbol_index_balance = index_amounts[index]
            if balance < base_symbol_volume + base_symbol_index_balance:
                available = balance - base_symbol_index_balance
                insufficient = True
                if available > 0.98 * base_symbol_volume:
                    corrected_volume = available
                    problems['description'] = f'Available {self.bot_config.trading_bot_config.base_symbol.upper()} is slightly lower than your order volume, lowering the volume by that amount!'
                    problems['adjusted_volume'] = corrected_volume
                else:
                    balance_string = f'{print_crypto_amount(balance-base_symbol_index_balance)} {self.bot_config.trading_bot_config.base_symbol.upper()}'
                    balance_base_curr = self.analytics.base_symbol_to_base_currency(balance-base_symbol_index_balance)
                    volume_base_curr = self.analytics.base_symbol_to_base_currency(base_symbol_volume)
                    volume_string = f'{print_crypto_amount(base_symbol_volume)} {self.bot_config.trading_bot_config.base_symbol.upper()}'
                    problems['description'] = \
                    f'Insufficient funds to execute savings plan, you have {balance_string} ({balance_base_curr:.2f} {self.bot_config.trading_bot_config.base_currency.values[1]})' + \
                    f' available over the ones in your portfolio.\nYou need {volume_string} ({volume_base_curr:.0f} {self.bot_config.trading_bot_config.base_currency.values[1]})'
        if insufficient:
            logger.warning(
                f"Insufficient funds to execute savings plan! You have {balance:.2f}" +
                f" {self.bot_config.trading_bot_config.base_symbol.upper()}")
            problems['occurred'] = True
            if problems.get('adjusted_volume', False):
                problems['fail'] = False
            else:
                problems['fail'] = True
        return problems

    # filter only tickers that are available on the exchange
    def filter_available(self, symbols: Union[np.ndarray, List]):
        available = [symbol for symbol in symbols if self.is_available(symbol)]
        return available

    def is_available(self, base_currency: str, quote_currency: str = None):
        if quote_currency is None:
            quote_currency = self.bot_config.trading_bot_config.base_symbol.upper()
        if base_currency.upper() == quote_currency.upper():
            return True
        return f'{base_currency.upper()}/{quote_currency}' in self.exchanges.active.markets


    def check_order_limits(self, symbols: np.ndarray, weights: np.ndarray, base_symbol_volume: float, fail_fast=False):
        volume_fail = []
        reason = []
        for symbol, weight in zip(symbols, weights):
            if symbol.lower() == self.bot_config.trading_bot_config.base_symbol.lower():
                continue
            ticker = f'{symbol.upper()}/{self.bot_config.trading_bot_config.base_symbol.upper()}'
            try:
                price = self.exchanges.active.fetch_ticker(ticker).get('last')
            except ccxt.errors.BadSymbol:
                logger.warning(f"Ticker {ticker} is not available on the exchange!")
                volume_fail.append(symbol)
                reason.append('Ticker not available')
                if fail_fast:
                    return volume_fail, reason
                continue
            cost = weight * base_symbol_volume
            amount = weight * base_symbol_volume / price

            if amount <= self.exchanges.active.markets[ticker]['limits']['amount']['min']:
                logger.warning(f"The amount of {amount} {ticker} at a price of {price} is too low to place an order!")
                volume_fail.append(symbol)
                reason.append('Order amount too low')
                if fail_fast:
                    return volume_fail, reason
            elif cost <= self.exchanges.active.markets[ticker]['limits']['cost']['min']:
                logger.warning(f"The cost of {cost} {self.bot_config.trading_bot_config.base_symbol.upper()}"
                               f" is too low to place an order!")
                volume_fail.append(symbol)
                reason.append('Order cost too low')
                if fail_fast:
                    return volume_fail, reason

        return volume_fail, reason

    # Place a weighted market buy order on Binance for multiple coins
    def weighted_buy_order(self, symbols: np.ndarray, weights: np.ndarray, base_currency_volume: float = None,
                           order_type: OrderTypeEnum = OrderTypeEnum.market) -> dict:
        volume = base_currency_volume or self.bot_config.trading_bot_config.savings_plan_cost  # order volume denoted in base currency
        volume = self.analytics.base_currency_to_base_symbol(volume)
        print_order_allocation(symbols, weights)
        self.exchanges.active.load_markets()
        report = {'problems': self.check_order_executable(symbols, weights, volume), 'order_ids': []}
        if report['problems']['fail']:
            return report

        # possibly adjust volume
        volume = report['problems'].get('adjusted_volume', volume)

        invalid = []
        placed_ids = []
        placed_symbols = []

        # Start buying
        # before = self.exchanges.active.fetch_total_balance()
        for symbol, weight in zip(symbols, weights):
            if symbol.lower() == self.bot_config.trading_bot_config.base_symbol.lower():
                logger.info(f"Skipping order for {symbol.upper()} as it equals the base symbol you are buying with")
                placed_symbols.append(symbol.upper())
                placed_ids.append(-weight*volume)  # storing the imagined cost of this order as a negative id as suboptimal workaround
                continue
            ticker = f'{symbol.upper()}/{self.bot_config.trading_bot_config.base_symbol.upper()}'
            price = self.exchanges.active.fetch_ticker(ticker).get('last')
            limit_price = 0.998*price
            amount = weight * volume / price
            try:
                if order_type == OrderTypeEnum.limit:
                    order = self.exchanges.active.create_limit_buy_order(ticker, amount, price=limit_price)
                elif order_type == OrderTypeEnum.market:
                    order = self.exchanges.active.create_market_buy_order(ticker, amount)
                else:
                    raise ValueError(f"Invalid order type: {order_type}")
            except ccxt.InvalidOrder as e:
                logger.error(f"Buy order for {amount} {ticker} is invalid!")
                logger.error(e)
                invalid.append(symbol)
                continue
            except ccxt.BaseError as e:
                logger.error(f"Error during order for {amount} {ticker}!")
                logger.error(e)
                continue
            else:
                logger.info(f"Placed order for {order['amount']:5f} {ticker} at {order['price']:.2f} $")
                placed_symbols.append(ticker)
                placed_ids.append(int(order['id']))

        report['order_ids'] = placed_ids
        report['symbols'] = placed_symbols
        report['invalid_symbols'] = invalid
        # # Report state of portfolio before and after buy orders
        # after = self.exchanges.active.fetch_total_balance()
        return report

    def check_orders(self, order_ids: List, symbols: List) -> dict:
        logger.info("Checking order status...")
        closed_orders = []
        open_orders = []
        order_report = {symbol: {} for symbol in symbols}
        for id, symbol in zip(order_ids, symbols):
            if id < 0:
                # this is a 'fake' order, when buying coin equals the base symbol we are using to buy the index
                logger.info("Checking dummy order")
                order_report[symbol]['status'] = 'closed'
                price = 1
                cost = -1 * id  # the imagined cost of this order is stored in place of the id of regular orders
                amount = cost
                date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                buy_symbol = symbol.upper()
                sell_symbol = symbol.upper()
                fee = 0
                fee_symbol = ''
            else:
                logger.info(f'Getting status of {symbol} order...')
                with retrying(self.exchanges.active.fetch_order, sleeptime=30, sleepscale=1, jitter=0,
                              retry_exceptions=(ccxt.errors.BaseError,)) as fetch_order:
                    order = fetch_order(id, symbol)
                if order['status'] == 'open':
                    logger.info(f"{symbol} order is not yet closed!")
                    order_report['symbol'] = 'open'
                    open_orders.append(symbol)
                    continue
                logger.info(f"{symbol} order closed!")
                try:
                    order_report[symbol]['status'] = 'closed'
                    price = order['price']
                    amount = order['amount']
                    cost = order['cost']
                    date = datetime.fromtimestamp(order['timestamp']/1000.0).strftime('%Y-%m-%d %H:%M:%S')
                    buy_symbol = order['symbol'].split('/')[0]
                    sell_symbol = order['symbol'].split('/')[1]
                    if order['fee'] is None:
                        fee = 0
                        fee_symbol = ''
                    else:
                        fee = order['fee']['cost']
                        fee_symbol = order['fee']['currency']
                except KeyError:
                    logger.error(f"KeyError while checking {symbol} order status!")
                    order_report['symbol'] = 'open'
                    open_orders.append(symbol)
                    continue
            order_report[symbol]['price'] = price
            order_report[symbol]['cost'] = cost
            closed_orders.append(symbol)
            logger.info(f"Adding {symbol} order to the trades file")
            try:
                self.analytics.add_trade(date=date,
                                         buy_symbol=buy_symbol,
                                         sell_symbol=sell_symbol,
                                         price=price,
                                         amount=amount,
                                         cost=cost,
                                         fee=fee,
                                         fee_symbol=fee_symbol,
                                         exchange=self.exchanges.active.name)
            except Exception as e:
                logger.error(f"Error while logging trade to trades.csv:")
                logger.error(e)
                raise e
        order_report['closed'] = closed_orders
        order_report['open'] = open_orders
        return order_report

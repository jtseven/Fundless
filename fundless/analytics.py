import asyncio
import math

import pandas as pd
from pathlib import Path
import pytz
import requests.exceptions
from pycoingecko import CoinGeckoAPI
from pydantic import validate_arguments
from pydantic.types import constr, Optional
import plotly.express as px
from typing import Tuple, Union, List
import numpy as np
from time import time, sleep
from redo import retrying
from threading import Lock
from datetime import datetime, timedelta
from threading import Thread
import logging
from currency_converter import CurrencyConverter
import ccxt

from config import Config, WeightingEnum, ExchangeEnum
from utils import print_crypto_amount
from constants import FIAT_SYMBOLS, COIN_REBRANDING, COIN_SYNONYMS, STABLE_COINS
from exchanges import Exchanges

logger = logging.getLogger(__name__)

date_time_regex = "(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})"

# TODO: Idea: translate exchange symbol names to coingecko symbol names to have one single source of truth (coingecko)
# translate coingecko symbols to ccxt/binance symbols
coingecko_symbol_dict = {"miota": "iota"}

title_size = 28
text_size = 20
min_font_size = 10


class PortfolioAnalytics:
    trades_df: pd.DataFrame
    trades_file: Path
    order_ids: pd.DataFrame
    order_ids_file: Path
    index_df: pd.DataFrame = None
    history_df: pd.DataFrame = None
    coingecko: CoinGeckoAPI
    markets: pd.DataFrame  # CoinGecko Market Data
    top_non_stablecoins: pd.DataFrame
    running_updates = False

    last_market_update: float = 0  # seconds since epoch
    last_history_update_month: float = 0  # seconds since epoch
    last_history_update_day: float = 0
    history_update_lock = Lock()
    last_trades_update: float = 0

    def __init__(
        self,
        trades_file: Union[str, Path],
        order_ids_file: Union[str, Path],
        config: Config,
        exchanges: Exchanges,
    ):
        self.config = config
        self.init_config_parameters()
        self.trades_file = Path(trades_file)
        self.order_ids_file = Path(order_ids_file)
        self.coingecko = CoinGeckoAPI()
        self.exchanges = exchanges
        self.exchange_balance = None

        if not self.trades_file.exists():
            self.trades_df = pd.DataFrame(columns=self.trades_cols)
            self.trades_df.to_csv(self.trades_file, index=False)
            self.last_trades_update = time()
        if not self.order_ids_file.exists():
            self.order_ids = pd.DataFrame(columns=["id", "symbol", "date"])
            self.order_ids.to_csv(self.order_ids_file, index=False)
        asyncio.run(self.update_data())  # Make sure all data is fetched initially
        self.run_api_updates()
        self.currency_converter = CurrencyConverter()

    def run_api_updates(self):
        def run_updates():
            while True:
                asyncio.run(self.update_data())
                sleep(5)

        updates = Thread(target=run_updates, daemon=True)
        updates.start()

    async def update_data(self):
        try:
            await asyncio.gather(
                self.update_markets(),
                self.update_order_ids(),
                self.update_trades_df(),
                self.update_index_df(),
                self.update_portfolio_metrics(),
                self.update_historical_prices(),
                self.update_exchange_balance(),
            )
        except (
            requests.exceptions.RequestException,
            ConnectionError,
            ccxt.NetworkError,
        ) as e:
            logger.warning("Network error while fetching data from an API:")
            logger.warning(e)
        except Exception as e:
            logger.error("Uncaught exception while updating analytics data!")
            logger.error(e)

    def init_config_parameters(self):
        self.base_cost_row = f"cost_{self.config.trading_bot_config.base_currency.value.lower()}"
        self.currency_symbol = self.config.trading_bot_config.base_currency.values[1]
        self.csv_dtypes = {
            "id": "str",
            "buy_symbol": "str",
            "sell_symbol": "str",
            "price": "float64",
            "amount": "float64",
            "cost": "float64",
            "fee": "float64",
            "fee_symbol": "str",
            self.base_cost_row: "float64",
            "date": "str",
            "cost_total": "float64",
        }
        self.trades_cols = [
            "date",
            "id",
            "buy_symbol",
            "sell_symbol",
            "price",
            "amount",
            "cost",
            "fee",
            "fee_symbol",
            "cost_total",
            self.base_cost_row,
            "exchange",
        ]

    def update_config(self, base_currency_changed: bool = False, index_changed: bool = False):
        self.init_config_parameters()
        if base_currency_changed:
            # update all market data again if base currency changed
            self.last_market_update = 0
            self.last_history_update_day = 0
            self.last_history_update_month = 0
        if index_changed:
            asyncio.run(self.update_index_df())

    def coin_available_on_exchange(self, coin: str):
        if coin.upper() == self.config.trading_bot_config.base_symbol.upper():
            return True
        return (
            f"{coin.upper()}/{self.config.trading_bot_config.base_symbol.upper()}" in self.exchanges.active.symbols
        )

    def available_index_coins(self):
        return [
            coin
            for coin in self.config.trading_bot_config.cherry_pick_symbols
            if self.coin_available_on_exchange(coin)
        ]

    def available_quote_currency(self, convert_to_accounting_currency=True, force_update=False) -> float:
        if self.exchange_balance is None or force_update:
            asyncio.run(self.update_exchange_balance())
        if convert_to_accounting_currency:
            return self.exchange_balance["converted"].get(self.config.trading_bot_config.base_symbol.upper(), 0.0)
        else:
            return self.exchange_balance["amount"].get(self.config.trading_bot_config.base_symbol.upper(), 0.0)

    async def update_exchange_balance(self):
        balance = {
            "amount": {},
            "converted": {},
        }  # amount: amount of coin, converted: amount in accounting currency
        balances = self.exchanges.active.fetch_total_balance(
            {"limit": 250} if self.config.trading_bot_config.exchange == ExchangeEnum.coinbase else None
        )
        symbols = np.fromiter([key for key in balances.keys() if balances[key] > 0.0], dtype="U10")
        amounts = np.fromiter([balances.get(symbol, 0.0) for symbol in symbols], dtype=float)
        balance["amount"] = {symbol.upper(): amount for symbol, amount in zip(symbols, amounts)}
        balances["converted"] = {
            symbol.upper(): self.convert(amount, symbol, self.config.trading_bot_config.base_currency)
            for symbol, amount in zip(symbols, amounts)
        }
        self.exchange_balance = balances

    # for cryptos that might have rebranded and changed their ticker some time
    def get_alternative_crypto_symbols(self, symbol: str) -> [str]:
        symbol = symbol.upper()
        found = [symbol in synonyms for synonyms in COIN_SYNONYMS]
        if any(found):
            found_index = np.where(found)[0]
            alternatives = [syn for syn in COIN_SYNONYMS[found_index[0]] if syn != symbol]
            logger.debug(f"Found alternatives for {symbol}:")
            logger.debug(alternatives)
            return alternatives
        else:
            logger.debug(f"Found no alternatives for {symbol}:")
            return []

    def get_coin_id(self, symbol: str):
        symbol = symbol.lower()
        try:
            coin_id = self.markets.loc[self.markets["symbol"] == symbol, ["id"]].values[0][0]
        except IndexError as e:
            alternatives = self.get_alternative_crypto_symbols(symbol)
            if len(alternatives) > 0:
                for alt in alternatives:
                    try:
                        coin_id = self.markets.loc[self.markets["symbol"] == alt.lower(), ["id"]].values[0][0]
                    except IndexError:
                        continue
                    else:
                        return coin_id
            logger.error(f"Could not find market data for {symbol.upper()}")
            raise e
        return coin_id

    def get_coin_name(self, symbol: str, abbr=False):
        if symbol.upper() in FIAT_SYMBOLS:
            return symbol
        symbol = symbol.lower()
        try:
            coin_name = self.markets.loc[self.markets["symbol"] == symbol, ["name"]].values[0][0]
        except IndexError as e:
            logger.warning(f"No coin name found in Coingecko market data for {symbol.upper()}!")
            alternatives = self.get_alternative_crypto_symbols(symbol)
            if len(alternatives) > 0:
                for alt in alternatives:
                    try:
                        coin_name = self.markets.loc[self.markets["symbol"] == alt.lower(), ["name"]].values[0][0]
                    except IndexError:
                        continue
                    else:
                        if abbr:
                            coin_name = coin_name[:14] + ".." if len(coin_name) > 14 else coin_name
                        return coin_name
            logger.error(
                f"Could not find market data for {symbol.upper()}. This could be because the coin is not within the top 250 coins on coingecko!"
            )
            coin_name = symbol.upper()
        if abbr:
            coin_name = coin_name[:14] + ".." if len(coin_name) > 14 else coin_name
        return coin_name

    def get_coin_image(self, symbol: str):
        symbol = symbol.lower()
        try:
            image = self.markets.loc[self.markets["symbol"] == symbol, ["image"]].values[0][0]
        except IndexError:
            logger.warning(f"No image found for coin {symbol.upper()}!")
            return "assets/coins-solid.png"
        return image

    def convert(self, amount: float, from_symbol: str, to_symbol: str):
        from_symbol = from_symbol.upper()
        to_symbol = to_symbol.upper()
        if math.isnan(amount):
            return 0
        if from_symbol == to_symbol:
            # nothing to convert
            return amount
        elif from_symbol in FIAT_SYMBOLS and to_symbol in FIAT_SYMBOLS:
            # convert fiat to fiat
            return self.currency_converter.convert(amount, from_symbol, to_symbol)
        elif from_symbol in FIAT_SYMBOLS:
            # convert fiat to crypto
            to_symbol_price = self.get_crypto_price(to_symbol, from_symbol)
            return amount / to_symbol_price
        else:
            # convert crypto to crypto/fiat
            from_symbol_price = self.get_crypto_price(from_symbol, to_symbol)
            return amount * from_symbol_price

    def get_crypto_price(self, crypto: str, vs_currency: str):
        crypto_id = self.get_coin_id(crypto)
        if vs_currency.lower() == self.config.trading_bot_config.base_currency.lower():
            price = self.markets.loc[self.markets["id"] == crypto_id, ["current_price"]].values[0][0]
        else:
            with retrying(
                self.coingecko.get_price,
                sleeptime=1,
                sleepscale=2,
                jitter=0,
                retry_exceptions=(requests.exceptions.HTTPError,),
            ) as get_price:
                price = get_price(crypto_id, vs_currencies=vs_currency.lower())[crypto_id][vs_currency.lower()]
        return price

    def base_symbol_to_base_currency(self, base_symbol_amount: float):
        base_currency = self.config.trading_bot_config.base_currency.value.upper()
        base_symbol = self.config.trading_bot_config.base_symbol.upper()
        return self.convert(base_symbol_amount, base_symbol, base_currency)

    def base_currency_to_base_symbol(self, base_currency_amount: float):
        base_currency = self.config.trading_bot_config.base_currency.value.upper()
        base_symbol = self.config.trading_bot_config.base_symbol.upper()
        return self.convert(base_currency_amount, base_currency, base_symbol)

    async def update_trades_df(self):
        if self.last_trades_update < time() - 60:
            trades_df = pd.read_csv(self.trades_file, dtype=self.csv_dtypes, parse_dates=["date"])
            trades_df.date = pd.to_datetime(trades_df.date, utc=True)

            if len(trades_df) > 0:
                if trades_df["date"].iloc[0].tzinfo is None:
                    trades_df["date"] = trades_df["date"].dt.tz_localize("UTC", ambiguous="infer")

            update_file = False

            for col in self.trades_cols:
                if col not in trades_df.columns:
                    logger.warning(f"Column: {col} not in trades.csv, adding it.")
                    trades_df.insert(loc=self.trades_cols.index(col), column=col, value=np.nan)
                    update_file = True

            # check for missing orders (that are in order_ids.csv but not in trades.csv)
            missing_ids = self.order_ids.loc[~self.order_ids["id"].isin(trades_df["id"])]
            if len(missing_ids) > 0:
                logger.warning("Found orders in orders.csv that are not in trades.csv!")
                logger.warning("Adding them to trades.csv")
                for id, symbol, date in zip(
                    missing_ids["id"].values,
                    missing_ids["symbol"].values,
                    missing_ids["date"].values,
                ):

                    if (
                        date.astype(np.int64)
                        > (pd.Timestamp.now(tz="Europe/Berlin") - pd.Timedelta(minutes=10)).value
                    ):
                        logger.info(f"Skipping order {id}, as it will be added by the savings plan bot.")
                        # skip orders, that are new, as they are still pending to be added regularly
                        continue
                    with retrying(
                        self.exchanges.active.fetch_order,
                        sleeptime=30,
                        sleepscale=1,
                        jitter=0,
                        retry_exceptions=(ccxt.errors.BaseError,),
                    ) as fetch_order:
                        order = fetch_order(id, symbol)
                        if order["status"] == "open":
                            logger.info(f"Order {id} is not yet closed!")
                            continue
                        else:
                            logger.info(f"Order {id} closed, adding to trades.csv")
                            trades_df = self.add_trade(
                                trades_df=trades_df,
                                date=datetime.fromtimestamp(order["timestamp"] / 1000.0).strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                ),
                                id=str(id),
                                buy_symbol=order["symbol"].split("/")[0],
                                sell_symbol=order["symbol"].split("/")[1],
                                price=order["price"],
                                amount=order["amount"],
                                cost=order["cost"],
                                fee=order["fee"]["cost"] if order["fee"] is not None else 0.0,
                                fee_symbol=order["fee"]["currency"] if order["fee"] is not None else "",
                                exchange=self.config.trading_bot_config.exchange,
                            )
                            update_file = True

            # compute total cost if missing
            trades_df["fee"].fillna(0.0, inplace=True)
            if any(trades_df["cost_total"].isna()):
                trades_df["cost_total"] = trades_df["cost"] + trades_df["fee"]

            # base_cost_row has the cost denoted in base_currency rather than buy_symbol
            def compute_base_cost(row):
                accounting_currency = self.config.trading_bot_config.base_currency.value.lower()
                date = row.date.strftime("%d-%m-%Y")
                if row.sell_symbol not in FIAT_SYMBOLS:
                    coin_id = self.get_coin_id(row.sell_symbol)  # TODO support for fiat as sell_symbol
                else:
                    coin_id = row.sell_symbol

                def convert_cost():
                    if row.sell_symbol.lower() != accounting_currency:
                        # TODO use convert method (implement historic prices in convert method)
                        return (
                            self.coingecko.get_coin_history_by_id(coin_id, date=date, localization=False)[
                                "market_data"
                            ]["current_price"][accounting_currency]
                            * row.cost_total
                        )
                    else:
                        return row.cost_total

                with retrying(
                    convert_cost,
                    sleeptime=20,
                    sleepscale=1,
                    jitter=0,
                    retry_exceptions=(requests.exceptions.HTTPError,),
                ) as get_base_cost:
                    base_cost = get_base_cost()

                return base_cost

            # add cost of trades in currently selected currency, it it's not there yet
            if self.base_cost_row in trades_df.columns:
                if trades_df[self.base_cost_row].isnull().values.any():
                    trades_df.loc[trades_df[self.base_cost_row].isnull(), self.base_cost_row] = trades_df.loc[
                        trades_df[self.base_cost_row].isnull()
                    ].apply(lambda row: compute_base_cost(row), axis=1)
                    update_file = True
            else:
                logger.info(
                    "Updating your trades file with historic cost in base currency, this will take a while "
                    "but is only performed once!"
                )
                trades_df[self.base_cost_row] = trades_df.apply(lambda row: compute_base_cost(row), axis=1)
                update_file = True

            # add column for used exchange, if it's not there yet
            if "exchange" in trades_df.columns:
                if trades_df["exchange"].isnull().values.any():
                    trades_df.loc[
                        trades_df["exchange"].isnull(), "exchange"
                    ] = self.config.trading_bot_config.exchange.value
                    update_file = True
            else:
                trades_df["exchange"] = self.config.trading_bot_config.exchange.value
                update_file = True

            # check if a coin has been rebranded and the old name is still used in the file
            if trades_df["buy_symbol"].isin(pd.Series(COIN_REBRANDING.keys())).any():
                trades_df["buy_symbol"].replace(COIN_REBRANDING, inplace=True)
                trades_df["sell_symbol"].replace(COIN_REBRANDING, inplace=True)
                update_file = True

            trades_df.date = pd.to_datetime(trades_df.date, utc=True)
            self.trades_df = trades_df
            self.last_trades_update = time()
            if update_file:
                self.update_trades_file()

    def update_trades_file(self):
        self.trades_df.sort_values("date", inplace=True)
        self.trades_df.to_csv(self.trades_file, index=False)

    def add_order_id(self, id: str, symbol: str, date: Union[str, datetime]):
        date = pd.to_datetime(date, infer_datetime_format=True)
        if date.tzinfo is None:
            date = date.tz_localize("Europe/Berlin")
        else:
            date = date.tz_convert("Europe/Berlin")
        id_dict = {"id": [id], "symbol": [symbol], "date": [date]}
        id_df = pd.DataFrame.from_dict(id_dict)
        self.order_ids = pd.concat([self.order_ids, id_df], ignore_index=True)
        self.update_order_ids_file()

    async def update_order_ids(self):
        self.order_ids = pd.read_csv(self.order_ids_file, index_col=False, parse_dates=["date"])
        self.order_ids.date = pd.to_datetime(self.order_ids.date, utc=True)
        if len(self.order_ids) > 0:
            if self.order_ids["date"].iloc[0].tzinfo is None:
                self.order_ids["date"] = self.order_ids["date"].dt.tz_localize("UTC", ambiguous="infer")

    def update_order_ids_file(self):
        self.order_ids.sort_values("date", inplace=True)
        self.order_ids.to_csv(self.order_ids_file, index=False)

    async def update_markets(self, force=False):
        if not force:
            # do not update, if last update 2 seconds ago
            if self.last_market_update >= time() - 2:
                return

        # update market data from coingecko
        try:
            with retrying(
                self.coingecko.get_coins_markets,
                sleeptime=20,
                sleepscale=1,
                jitter=0,
                retry_exceptions=(requests.exceptions.HTTPError,),
            ) as get_markets:
                markets = pd.DataFrame.from_records(
                    get_markets(
                        vs_currency=self.config.trading_bot_config.base_currency.value,
                        per_page=250,
                    )
                )
                more_markets = pd.DataFrame.from_records(
                    get_markets(
                        vs_currency=self.config.trading_bot_config.base_currency.value, per_page=250, page=2
                    )
                )
                markets = pd.concat([markets, more_markets], ignore_index=True)
                markets["symbol"] = markets["symbol"].str.lower()
        except requests.exceptions.HTTPError as e:
            logger.error("Network error while updating market data from CoinGecko:")
            logger.error(e)
            return
        markets.replace(coingecko_symbol_dict, inplace=True)
        self.markets = markets
        self.top_non_stablecoins = markets.loc[~markets.symbol.str.upper().isin(STABLE_COINS)]
        self.last_market_update = time()

    async def update_index_df(self):
        # update index portfolio value
        other = pd.DataFrame(index=self.config.trading_bot_config.cherry_pick_symbols)
        index_df = (
            self.trades_df[["buy_symbol", "amount", self.base_cost_row]]
            .copy()
            .groupby("buy_symbol")
            .sum(numeric_only=True)
        )
        index_df.index = index_df.index.str.lower()
        index_df = pd.merge(index_df, other, how="outer", left_index=True, right_index=True)
        index_df.fillna(value=0, inplace=True, axis="columns")
        index_df = self.markets[["symbol", "current_price"]].join(index_df, on="symbol", how="inner")
        index_df["value"] = index_df["current_price"] * index_df["amount"]
        index_df["allocation"] = index_df["value"] / index_df["value"].sum()
        index_df["symbol"] = index_df["symbol"].str.upper()
        index_df["performance"] = index_df["value"] / index_df[self.base_cost_row] - 1
        self.index_df = index_df

    @validate_arguments
    def add_trade(
        self,
        date: Union[constr(regex=date_time_regex), datetime],
        id: str,
        buy_symbol: str,
        sell_symbol: str,
        price: float,
        amount: float,
        cost: float,
        fee: Optional[float],
        fee_symbol: Optional[str],
        base_cost: Optional[float] = None,
        exchange: Optional[ExchangeEnum] = None,
        trades_df=None,
    ):
        if base_cost is None:
            base_cost = self.base_symbol_to_base_currency(cost)
        if fee is None:
            fee = 0
        if fee_symbol is None:
            fee_symbol = ""
        if exchange is None:
            exchange = self.config.trading_bot_config.exchange
        date = pd.to_datetime(date, infer_datetime_format=True)
        if date.tzinfo is None:
            date = date.tz_localize("Europe/Berlin")
        else:
            date = date.tz_convert("Europe/Berlin")

        trade_dict = {
            "date": [date],
            "id": [id],
            "buy_symbol": [buy_symbol.upper()],
            "sell_symbol": [sell_symbol.upper()],
            "price": [price],
            "amount": [amount],
            "cost": [cost],
            "fee": [fee],
            "fee_symbol": [fee_symbol.upper()],
            self.base_cost_row: [base_cost],
            "exchange": exchange.value,
        }
        trade_dict_df = pd.DataFrame.from_dict(trade_dict)
        if trades_df is not None:
            trades_df = pd.concat([trades_df, trade_dict_df], ignore_index=True)
            return trades_df
        else:
            self.trades_df = pd.concat([self.trades_df, trade_dict_df], ignore_index=True)
            self.update_trades_file()

    async def index_balance(self) -> Tuple:
        await self.update_markets()
        if self.index_df is None:
            return None, None, None, None
        index = self.index_df.sort_values(by="allocation", ascending=False)
        allocations = index["allocation"].values * 100
        symbols = index["symbol"].values
        values = index["value"].values
        amounts = index["amount"].values
        return symbols, amounts, values, allocations

    @property
    def performance(self) -> float:
        if self.trades_df is None or self.index_df is None:
            return 0
        amount_invested = self.trades_df[self.base_cost_row].sum()
        portfolio_value = self.index_df.value.sum()
        return portfolio_value / amount_invested - 1

    @property
    def invested(self) -> float:
        if self.trades_df is None:
            return 0
        return self.trades_df[self.base_cost_row].sum()

    @property
    def net_worth(self) -> float:
        if self.index_df is None:
            return 0
        return self.index_df.value.sum()

    @property
    def pretty_index_df(self):
        df = pd.DataFrame()
        if self.index_df is None:
            return df
        self.index_df.sort_values(by="allocation", ascending=False, inplace=True)
        value_format = f"{self.config.trading_bot_config.base_currency.values[1]} {{:,.2f}}"
        df["Coin"] = self.index_df["symbol"]
        df["Currently in Index"] = self.index_df["symbol"].map(
            lambda sym: "yes" if sym.lower() in self.config.trading_bot_config.cherry_pick_symbols else "no"
        )
        df[f"Available"] = self.index_df["symbol"].map(
            lambda sym: "yes" if self.coin_available_on_exchange(sym) else "no"
        )
        df["Amount"] = self.index_df["amount"].map(print_crypto_amount)
        df["Allocation"] = self.index_df["allocation"].map("{:.2%}".format)
        _, target_allocation = self.fetch_index_weights(symbols=df["Coin"])
        df["Target Allocation"] = target_allocation
        df["Target Allocation"] = df["Target Allocation"].map(lambda row: f"{row:.2%}" if row != 0 else "-")
        df["Value"] = self.index_df["value"].map(value_format.format)
        df["Performance"] = self.index_df["performance"].fillna(0).map("{:.2%}".format)
        return df

    def allocation_pie(self, as_image=False, title=True):
        if self.index_df is None:
            return {}
        allocation_df = self.index_df.copy()

        fig = px.pie(
            allocation_df,
            values="allocation",
            names="symbol",
            color_discrete_sequence=px.colors.sequential.Viridis,
            hole=0.6,
        )
        fig.update_traces(textposition="inside", textinfo="label", hoverinfo="label+percent")
        fig.update_layout(
            showlegend=False,
            title={"xanchor": "center", "x": 0.5},
            uniformtext_minsize=min_font_size,
            uniformtext_mode="hide",
            annotations=[
                dict(
                    text=f"{allocation_df['value'].sum():,.2f} {self.config.trading_bot_config.base_currency.values[1]}",
                    x=0.5,
                    y=0.5,
                    font_size=text_size,
                    showarrow=False,
                )
            ],
            title_font=dict(size=title_size),
            margin=dict(l=20, r=20, t=20, b=20),
        )
        if title:
            fig.update_layout(title="Coin Allocation")
        if as_image:
            return fig.to_image(format="png", width=600, height=600)
        else:
            return fig

    async def update_historical_prices(self):
        if self.last_market_update == 0:
            return
        to_timestamp = time()
        freq = None
        month = 60 * 60 * 24 * 30
        day = 60 * 60 * 24
        if self.history_df is None:
            # get full history from api
            min_time = (self.trades_df["date"].min() - pd.DateOffset(2)).timestamp()
            from_timestamp = min_time
        elif self.last_history_update_month < time() - 60 * 60 * 24 * 2:  # t - 2days
            # get data from last month
            from_timestamp = time() - month
            freq = "H"
            self.last_history_update_month = time()
        elif self.last_history_update_day < time() - 60 * 15:  # t - 15min
            from_timestamp = time() - day
            self.last_history_update_day = time()
            freq = "5T"  # 5 minutes
        else:
            # no update needed
            return

        with self.history_update_lock:
            # pull historic market data for all coins (pretty heavy on API requests)
            for coin in self.index_df["symbol"].str.lower():
                id = self.markets.loc[self.markets["symbol"] == coin, ["id"]].values[0][0]
                try:
                    with retrying(
                        self.coingecko.get_coin_market_chart_range_by_id,
                        sleeptime=30,
                        sleepscale=1,
                        jitter=0,
                        retry_exceptions=(requests.exceptions.HTTPError,),
                    ) as get_history:
                        data = get_history(
                            id=id,
                            vs_currency=self.config.trading_bot_config.base_currency.value,
                            from_timestamp=from_timestamp,
                            to_timestamp=to_timestamp,
                        )
                except requests.exceptions.HTTPError as e:
                    logger.error("Error while updating historic prices from API")
                    logger.error(e)
                    return
                data_df = pd.DataFrame.from_records(data["prices"], columns=["timestamp", f"{coin}"])
                data_df["timestamp"] = pd.to_datetime(data_df["timestamp"], unit="ms", utc=True)
                data_df.set_index("timestamp", inplace=True)
                if "history_df" not in locals():
                    history_df = data_df
                else:
                    history_df = history_df.join(data_df, how="outer")

            if freq is not None:
                # round datetime index to given frequency,
                # otherwise all coins have price data at slightly different times
                history_df = (
                    history_df.fillna(method="ffill")
                    .fillna(method="bfill")
                    .reindex(history_df.index.round(freq).drop_duplicates(), method="nearest")
                )
                if freq == "H":
                    truncate_from = pd.to_datetime(from_timestamp, unit="s", utc=True)
                    truncate_to = pd.to_datetime(to_timestamp - day, unit="s", utc=True)
                elif freq == "5T":
                    truncate_from = pd.to_datetime(to_timestamp - day, unit="s", utc=True)
                    truncate_to = pd.to_datetime(time(), unit="s", utc=True)
            else:
                truncate_from = pd.to_datetime(time(), unit="s", utc=True)
                truncate_to = truncate_from

            # add most recent prices for data consistency
            current_prices = [
                self.markets.loc[self.markets["symbol"] == symbol, ["current_price"]].values[0][0]
                for symbol in list(history_df.columns)
            ]
            now_row = pd.DataFrame(
                [current_prices],
                columns=history_df.columns,
                index=[pd.Timestamp.now(tz="utc")],
            )
            history_df = pd.concat([history_df, now_row]).sort_index()

            if self.history_df is not None:
                mask = (self.history_df.index < truncate_from) | (self.history_df.index > truncate_to)
                history_df = pd.concat([history_df, self.history_df.loc[mask]])
                history_df = history_df[~history_df.index.duplicated(keep="first")].sort_index()
            self.history_df = history_df

    def compute_value_history(self, from_timestamp=None):
        if self.history_df is None:
            raise ValueError
        if from_timestamp is not None:
            start_time = pd.to_datetime(from_timestamp, unit="s", utc=True)
            price_history = self.history_df.copy().truncate(before=start_time)
        else:
            price_history = self.history_df.copy()
            start_time = price_history.index.min()
        if start_time < (pd.Timestamp.now(tz="utc") - pd.DateOffset(days=31)):
            freq = "D"
        elif start_time < (pd.Timestamp.now(tz="utc") - pd.DateOffset(days=14, minutes=2)):
            freq = "3H"
        elif start_time < (pd.Timestamp.now(tz="utc") - pd.DateOffset(days=1, minutes=2)):
            freq = "H"
        else:
            freq = "5T"  # 5 minutes

        price_history = price_history.resample(freq, origin="end").ffill()
        # add most recent prices for data consistency
        current_prices = [
            self.markets.loc[self.markets["symbol"] == symbol, ["current_price"]].values[0][0]
            for symbol in list(price_history.columns)
        ]
        current_prices = pd.DataFrame(
            [current_prices],
            columns=price_history.columns,
            index=[pd.Timestamp.now(tz="utc")],
        )
        price_history = pd.concat([price_history, current_prices]).sort_index()
        if start_time + pd.Timedelta(days=2) < price_history.index.min():
            zero_row = pd.DataFrame(0, index=[start_time], columns=price_history.columns)
            price_history = pd.concat([price_history, zero_row]).sort_index()
        price_history.index = pd.to_datetime(price_history.index, utc=True).tz_convert(tz="Europe/Berlin")

        invested = (
            self.trades_df[["date", "buy_symbol", self.base_cost_row]]
            .groupby(["date", "buy_symbol"], as_index=False, axis=0)
            .sum(numeric_only=True)
        )
        value = (
            self.trades_df[["date", "buy_symbol", "amount"]]
            .groupby(["date", "buy_symbol"], as_index=False, axis=0)
            .sum(numeric_only=True)
        )
        invested = invested.pivot(index="date", columns="buy_symbol", values=self.base_cost_row)
        invested = invested.cumsum().fillna(method="ffill").fillna(0)
        invested = invested.reindex(price_history.index, method="ffill").fillna(0)
        invested.columns = invested.columns.str.lower()

        value = value.pivot(index="date", columns="buy_symbol", values="amount")
        value = value.cumsum().fillna(method="ffill").fillna(0)
        value = value.reindex(price_history.index, method="ffill").fillna(0)
        value.columns = value.columns.str.lower()
        value = value * price_history

        return value, invested

    def value_history_chart(self, as_image=False, from_timestamp=None, title=True):
        try:
            value, invested = self.compute_value_history(from_timestamp=from_timestamp)
        except ValueError:
            return {}
        performance_df = pd.DataFrame(index=value.index, columns=["invested", "net_worth"])
        performance_df["invested"] = invested.sum(axis=1)
        performance_df["net_worth"] = value.sum(axis=1)

        if performance_df["invested"].min() == performance_df["invested"].max():
            y = ["net_worth"]
            color = [px.colors.sequential.Viridis[0]]
        else:
            y = ["invested", "net_worth"]
            color = ["gray", px.colors.sequential.Viridis[0]]

        fig = px.line(
            performance_df,
            x=performance_df.index,
            y=y,
            line_shape="spline",
            render_mode="svg",
            color_discrete_sequence=color,
        )

        fig.update_traces(selector=dict(name="invested"), line_shape="hv")
        fig.update_layout(
            showlegend=False,
            title={"xanchor": "center", "x": 0.5},
            uniformtext_minsize=min_font_size,
            uniformtext_mode="hide",
            title_font=dict(size=title_size),
            plot_bgcolor="white",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        fig.update_xaxes(showgrid=False, title_text="", fixedrange=True)
        fig.update_yaxes(
            side="right",
            showgrid=True,
            ticksuffix=f" {self.config.trading_bot_config.base_currency.values[1]}",
            title_text="",
            gridcolor="lightgray",
            gridwidth=0.15,
            fixedrange=True,
        )
        if title:
            fig.update_layout(title="Portfolio value")
        if as_image:
            return fig.to_image(format="png", width=1200, height=600)
        else:
            return fig

    def performance_chart(self, as_image=False, from_timestamp=None, title=True):
        try:
            value, invested = self.compute_value_history(from_timestamp=from_timestamp)
        except ValueError:
            return {}
        performance_df = pd.DataFrame(index=value.index, columns=["invested", "net_worth"])
        performance_df["invested"] = invested.sum(axis=1)
        performance_df["net_worth"] = value.sum(axis=1)
        performance_df["invested"] += performance_df["net_worth"].iloc[0] - performance_df["invested"].iloc[0]
        performance_df["performance"] = (performance_df["net_worth"] / performance_df["invested"] - 1) * 100
        performance_df.fillna(0, inplace=True)

        fig = px.line(
            performance_df,
            x=performance_df.index,
            y="performance",
            line_shape="spline",
            render_mode="svg",
            color_discrete_sequence=["green"],
        )
        fig.update_layout(
            showlegend=False,
            title={"xanchor": "center", "x": 0.5},
            uniformtext_minsize=min_font_size,
            uniformtext_mode="hide",
            title_font=dict(size=title_size),
            plot_bgcolor="white",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        fig.add_scatter(
            x=performance_df.index,
            y=performance_df.performance.where(performance_df.performance < 0),
            line={"color": "red", "shape": "spline"},
        )
        fig.update_xaxes(showgrid=False, title_text="", zeroline=True, fixedrange=True)
        fig.update_yaxes(
            side="right",
            showgrid=False,
            ticksuffix=" %",
            zeroline=True,
            zerolinecolor="lightgray",
            title_text="",
            zerolinewidth=0.2,
            fixedrange=True,
        )
        if title:
            fig.update_layout(title="Portfolio performance")
        if as_image:
            return fig.to_image(format="png", width=1200, height=600)
        else:
            return fig

    async def update_portfolio_metrics(self):
        top_gainers = self.index_df.nlargest(3, "performance")
        worst_gainers = self.index_df.nsmallest(3, "performance")
        # TODO could make these properties with @property decorator
        self.top_symbols = top_gainers["symbol"].values
        self.top_performances = top_gainers["performance"].values
        self.top_growth = top_gainers["value"].values - top_gainers[self.base_cost_row].values
        self.worst_symbols = worst_gainers["symbol"].values
        self.worst_performances = worst_gainers["performance"].values
        self.worst_growth = worst_gainers["value"].values - worst_gainers[self.base_cost_row].values

    @staticmethod
    def get_timestamp(value: str):
        now = datetime.now(pytz.timezone("Europe/Berlin"))
        if value == "day":
            timestamp = (now - timedelta(days=1)).timestamp()
        elif value == "week":
            timestamp = (now - timedelta(weeks=1)).timestamp()
        elif value == "month":
            timestamp = (now - timedelta(days=30)).timestamp()
        elif value == "6month":
            timestamp = (now - timedelta(days=182)).timestamp()
        elif value == "year":
            timestamp = (now - timedelta(days=365)).timestamp()
        else:
            timestamp = None
        return timestamp

        # Compute the weights by market cap, fetching data from coingecko
        # Square root weights yield a less top heavy distribution of coin allocation (lower bitcoin weighting)

    def fetch_index_weights(self, symbols: np.ndarray = None):
        if symbols is not None:
            symbols = np.asarray([symbol.lower() for symbol in symbols])
        else:
            symbols = np.asarray(self.config.trading_bot_config.cherry_pick_symbols)

        if self.config.trading_bot_config.portfolio_weighting == WeightingEnum.equal:
            weights = np.array(
                [
                    1 / len(self.config.trading_bot_config.cherry_pick_symbols)
                    if sym in self.config.trading_bot_config.cherry_pick_symbols
                    else 0.0
                    for sym in symbols
                ]
            )
        elif self.config.trading_bot_config.portfolio_weighting == WeightingEnum.custom:
            weights = np.zeros(len(symbols))
            for k, symbol in enumerate(symbols):
                if symbol in self.config.trading_bot_config.custom_weights:
                    weights[k] = self.config.trading_bot_config.custom_weights[symbol]
        else:
            weights = np.asarray(
                [
                    self.markets.loc[self.markets.symbol == sym, "market_cap"].item()
                    if sym in self.config.trading_bot_config.cherry_pick_symbols
                    else 0.0
                    for sym in symbols
                ]
            )
            if self.config.trading_bot_config.portfolio_weighting == WeightingEnum.sqrt_market_cap:
                weights = np.sqrt(weights)
            elif self.config.trading_bot_config.portfolio_weighting == WeightingEnum.sqrt_sqrt_market_cap:
                weights = np.sqrt(np.sqrt(weights))
            elif self.config.trading_bot_config.portfolio_weighting == WeightingEnum.cbrt_market_cap:
                weights = np.cbrt(weights)
        weights = weights / weights.sum()
        return symbols, weights

    # Export all trades in a Parqet (Portfolio Tool) compatible format
    def trades_csv_export(self, since: Optional[datetime] = None):
        cols = [
            "datetime",
            "price",
            "shares",
            "tax",
            "fee",
            "type",
            "assettype",
            "identifier",
            "currency",
        ]
        export = pd.DataFrame(columns=cols)
        export["datetime"] = self.trades_df["date"]
        export["price"] = self.trades_df["cost_eur"] / self.trades_df["amount"]
        export["shares"] = self.trades_df["amount"]
        export["tax"] = 0

        def get_fee(row: pd.Series):
            if row["fee"] == 0 or math.isnan(row["fee"]):
                return 0
            if (
                row["fee_symbol"] == "EUR"
                or len(str(row["fee_symbol"])) == 0
                or isinstance(row["fee_symbol"], float)
            ):
                # assuming that the fee is in euros if no other fee symbol is given!
                return row["fee"]
            return self.convert(row["fee"], row["fee_symbol"], "EUR")

        export["fee"] = self.trades_df[["fee", "fee_symbol"]].apply(get_fee, axis=1)
        export["type"] = "Buy"
        export["assettype"] = "Crypto"
        export["identifier"] = self.trades_df["buy_symbol"]
        export["currency"] = "EUR"
        if since is not None:
            export = export.loc[export["datetime"] >= since]
        return export

    """
    return: sorted array of top n non-stablecoin crypto by market cap
    """

    def top_n(self, n: int) -> List:
        return self.top_non_stablecoins.head(n).symbol.tolist()

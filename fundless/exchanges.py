import ccxt
from config import ExchangeEnum, Config
import logging

logger = logging.getLogger(__name__)


class Exchanges:
    authorized_exchanges: dict = {}
    active: ccxt.Exchange

    def __init__(self, config: Config):
        self.secrets = config.secrets
        self.trading_config = config.trading_bot_config

        for exchange_token in self.secrets.get_exchange_tokens(test_mode=self.trading_config.test_mode):
            if not self.init_exchange(exchange_name=exchange_token["exchange"]):
                logger.warning(f"No valid API tokens for exchange {exchange_token['exchange'].values[1]}")

        if self.trading_config.exchange not in self.authorized_exchanges.keys():
            raise RuntimeWarning(f"No valid API tokens for selected exchange {self.trading_config.exchange.values[1]}")
        else:
            self.active = self.authorized_exchanges[self.trading_config.exchange]

        logger.info("List of exchanges with validated API tokens:")
        logger.info([exchange.values[1] for exchange in self.authorized_exchanges.keys()])

    def init_exchange(
        self,
        exchange_name: ExchangeEnum,
    ) -> bool:
        if exchange_name == ExchangeEnum.binance:
            exchange = ccxt.binance()
            if self.trading_config.test_mode:
                exchange.apiKey = self.secrets.binance_test["api_key"]
                exchange.secret = self.secrets.binance_test["secret"]
            else:
                exchange.apiKey = self.secrets.binance["api_key"]
                exchange.secret = self.secrets.binance["secret"]
        elif exchange_name == ExchangeEnum.kraken:
            exchange = ccxt.kraken()
            if self.trading_config.test_mode:
                exchange.apiKey = self.secrets.kraken_test["api_key"]
                exchange.secret = self.secrets.kraken_test["secret"]
            else:
                exchange.apiKey = self.secrets.kraken["api_key"]
                exchange.secret = self.secrets.kraken["secret"]
        elif exchange_name == ExchangeEnum.coinbasepro:
            exchange = ccxt.coinbasepro()
            if self.trading_config.test_mode:
                return False  # Coinbase Pro does not have a test mode
            else:
                exchange.apiKey = self.secrets.coinbasepro["api_key"]
                exchange.secret = self.secrets.coinbasepro["secret"]
                exchange.password = self.secrets.coinbasepro["passphrase"]
        else:
            raise ValueError("Invalid Exchange given!")

        if "test" in exchange.urls.keys():
            exchange.set_sandbox_mode(self.trading_config.test_mode)
        elif self.trading_config.test_mode:
            # Test mode is enabled, but current exchange does not support it
            return False
        if not exchange.check_required_credentials():
            return False
        try:
            exchange.load_markets()
        except ccxt.AuthenticationError:
            return False
        self.authorized_exchanges[exchange_name] = exchange
        return True

        # not_available = [symbol.upper() for symbol in self.trading_config.cherry_pick_symbols if
        #                  f'{symbol.upper()}/{self.trading_config.base_symbol.upper()}' not in
        #                  self.exchange.symbols and symbol != self.trading_config.base_symbol]
        # if len(not_available) > 0:
        #     logger.warning(f'Some of your cherry picked coins are not available on {self.exchange.name}:')
        #     logger.warning(not_available)

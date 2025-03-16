import logging

import ccxt

from fundless.config import Config, ExchangeEnum, SecretsStore

logger = logging.getLogger(__name__)


class Exchanges:
    authorized_exchanges: dict = {}
    active: ccxt.Exchange
    secrets: SecretsStore

    def __init__(self, config: Config):
        self.secrets = config.secrets
        self.trading_config = config.trading_bot_config

        for exchange_token in self.secrets.get_exchange_tokens(test_mode=self.trading_config.test_mode):
            if not self.init_exchange(exchange_name=exchange_token.exchange):
                logger.warning(f"No valid API tokens for exchange {exchange_token.exchange.values[1]}")

        if self.trading_config.exchange not in self.authorized_exchanges.keys():
            raise RuntimeWarning(
                f"No valid API tokens for selected exchange {self.trading_config.exchange.values[1]}"
            )
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
                exchange.apiKey = self.secrets.binance_test.api_key
                exchange.secret = self.secrets.binance_test.secret
            else:
                exchange.apiKey = self.secrets.binance.api_key
                exchange.secret = self.secrets.binance.secret
        elif exchange_name == ExchangeEnum.kraken:
            exchange = ccxt.kraken()
            if self.trading_config.test_mode:
                exchange.apiKey = self.secrets.kraken_test.api_key
                exchange.secret = self.secrets.kraken_test.secret
            else:
                exchange.apiKey = self.secrets.kraken.api_key
                exchange.secret = self.secrets.kraken.secret
        elif exchange_name == ExchangeEnum.coinbase:
            try:
                # Initialize Coinbase with proper configuration
                coinbase_config = {
                    'apiKey': self.secrets.coinbase.api_key,
                    'secret': self.secrets.coinbase.secret,
                    # 'options': {
                    #     'createMarketBuyOrderRequiresPrice': False
                    # }
                }
                exchange = ccxt.coinbase(coinbase_config)
                
                # Skip test mode for Coinbase since it's not supported
                if self.trading_config.test_mode:
                    logger.warning("Coinbase does not support test mode")
                    return False
            except Exception as e:
                logger.error(f"Failed to initialize Coinbase: {str(e)}")
                return False
        else:
            raise ValueError("Invalid Exchange given!")

        # Check if sandbox/test mode is supported
        if hasattr(exchange, 'urls') and exchange.urls is not None and "test" in exchange.urls:
            exchange.set_sandbox_mode(self.trading_config.test_mode)
        elif self.trading_config.test_mode:
            # Test mode is enabled, but current exchange does not support it
            logger.warning(f"Test mode is enabled, but {exchange_name} does not support it")
            return False
                
        if not exchange.check_required_credentials(error=False):
            logger.error(f"Missing credentials for {exchange_name}")
            return False
            
        try:
            exchange.load_markets()
        except ccxt.AuthenticationError as e:
            logger.error(f"Authentication error for {exchange_name}: {str(e)}")
            return False
            
        self.authorized_exchanges[exchange_name] = exchange
        return True

        # not_available = [symbol.upper() for symbol in self.trading_config.cherry_pick_symbols if
        #                  f'{symbol.upper()}/{self.trading_config.base_symbol.upper()}' not in
        #                  self.exchange.symbols and symbol != self.trading_config.base_symbol]
        # if len(not_available) > 0:
        #     logger.warning(f'Some of your cherry picked coins are not available on {self.exchange.name}:')
        #     logger.warning(not_available)

from pathlib import Path
import sys
import yaml
from typing import List, Union, Dict, Optional
from pydantic import BaseModel
from pydantic.types import confloat, conint, constr
from pydantic import validator, root_validator
from aenum import MultiValueEnum
import logging

if sys.version_info >= (3, 8):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict


logger = logging.getLogger(__name__)


# Convention for multi value enums:
#   - value: used in config and code (string as defined by ccxt)
#   - values[1]: beautiful name for printing
#   - values[2:]: alternative names (might be used by user in config and interaction)
class ExchangeEnum(str, MultiValueEnum):
    binance = 'binance', 'Binance'
    kraken = 'kraken', 'Kraken'
    coinbasepro = 'coinbasepro', 'Coinbase Pro', 'coinbase_pro'


class LoginProviderEnum(str, MultiValueEnum):
    custom = 'custom', 'Custom', 'own'
    auth0 = 'auth0', 'Auth0', 'Auth 0', 'auth 0'


class BaseCurrencyEnum(str, MultiValueEnum):
    eur = 'EUR', '€', 'Euro', 'euro', 'eur'
    usd = 'USD', '$', 'US Dollar', 'usd', 'usdollar'
    btc = 'BTC', 'btc', 'Bitcoin', 'bitcoin'
    eth = 'ETH', 'eth', 'Ethereum', 'ethereum', 'ether'


class IntervalEnum(str, MultiValueEnum):
    daily = 'daily'
    weekly = 'weekly'
    biweekly = 'biweekly', 'bi-weekly'


class OrderTypeEnum(str, MultiValueEnum):
    market = 'market'
    limit = 'limit'


class WeightingEnum(str, MultiValueEnum):
    equal = 'equal'
    custom = 'custom'
    market_cap = 'market_cap', 'marketcap', 'market cap'
    sqrt_market_cap = 'sqrt_market_cap', 'square root market cap', 'sqrt market cap'
    cbrt_market_cap = 'cbrt_market_cap', 'cubic root market cap', 'cbrt market cap'
    sqrt_sqrt_market_cap = 'sqrt_sqrt_market_cap', 'sqrt sqrt market cap'


class PortfolioModeEnum(str, MultiValueEnum):
    cherry_pick = 'cherry_pick', 'pick', 'cherry pick', 'Cherry Pick', 'cherry_picked'
    index = 'index', 'Index'


class ExchangeToken(TypedDict, total=False):
    exchange: ExchangeEnum
    api_key: str
    secret: str
    passphrase: Optional[str]


class TelegramToken(TypedDict):
    token: str
    chat_id: str


class BaseConfig(BaseModel):
    class Config:
        json_encoders = {
            MultiValueEnum: lambda v: v.value,
        }
        validate_assignment = True

    def print_markdown(self):
        config_dict = self.dict()
        for key, value in config_dict.items():
            if isinstance(value, MultiValueEnum):
                config_dict[key] = value.value
        msg = "```\n"
        msg += yaml.dump(config_dict)
        msg += "\n```"
        return msg

    @classmethod
    def from_json(cls, file_path):
        return cls.parse_file(file_path)


class DashboardConfig(BaseConfig):
    dashboard: bool
    domain_name: str
    login_provider: LoginProviderEnum

    @classmethod
    def from_config_yaml(cls, file_path):
        file = Path(file_path)
        with open(file) as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                logger.error("Error while parsing config file:")
                logger.error(exc)
                raise exc
        config = data['dashboard']
        self = cls.from_dict(config)
        return self

    @classmethod
    def from_dict(cls, dictionary):
        self = cls(
            dashboard=dictionary['dashboard'],
            domain_name=dictionary.get('domain_name', 'localhost'),
            login_provider=dictionary['login_provider'].get('selected', LoginProviderEnum.custom)
        )
        return self


class TradingBotConfig(BaseConfig):
    exchange: ExchangeEnum
    test_mode: Optional[bool] = False
    base_currency: BaseCurrencyEnum
    base_symbol: constr(strip_whitespace=True, to_lower=True, regex='^(busd|usdc|usdt|usd|eur|btc)$')
    savings_plan_cost: confloat(gt=0, le=10000)
    savings_plan_interval: Union[IntervalEnum, List[conint(ge=1, le=28)]]
    savings_plan_execution_time: constr(regex='^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$')
    savings_plan_automatic_execution: Optional[bool] = False
    portfolio_mode: PortfolioModeEnum
    portfolio_weighting: WeightingEnum
    cherry_pick_symbols: Optional[List[constr(to_lower=True)]]
    custom_weights: Optional[Dict[constr(to_lower=True), float]]
    index_top_n: Optional[conint(gt=0, le=100)]
    index_exclude_symbols: Optional[List[constr(to_lower=True)]]
    # base_fiat_symbols: List[str]  # TODO define fiat symbols here instead of in trading.py
    # usd_symbols = ['usd', 'usdt', 'busd', 'usdc', 'dai']
    # eur_symbols = ['eur', 'eurt']

    @validator('base_currency')
    def check_if_currency_supported(cls, v):
        if v in (BaseCurrencyEnum.btc, BaseCurrencyEnum.eth):
            raise NotImplementedError("Only USD and EUR base currencies are supported by now")
        return v

    @validator('portfolio_mode')
    def check_if_portfolio_supported(cls, v):
        if v in (PortfolioModeEnum.index, ):
            raise NotImplementedError("Only cherry-picked portfolio is supported by now")
        return v

    @root_validator
    def check_custom_weights(cls, values):
        if values.get('portfolio_weighting') != WeightingEnum.custom:
            return values
        custom_weights = values.get('custom_weights', None)
        if custom_weights is None:
            return values
        elif values.get('portfolio_mode') == PortfolioModeEnum.cherry_pick:
            for symbol, weight in custom_weights.items():
                if symbol not in values.get('cherry_pick_symbols'):
                    raise ValueError(f"{symbol} defined in custom weights, but not in cherry picked symbols")
        return values

    @classmethod
    def from_config_yaml(cls, file_path):
        file = Path(file_path)
        with open(file) as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                logger.error("Error while parsing config file:")
                logger.error(exc)
                raise exc
        config = data['trading_bot']
        self = cls.from_dict(config)
        return self

    @classmethod
    def from_dict(cls, dictionary):

        self = cls(
            exchange=dictionary['exchange']['selected'],
            test_mode=dictionary.get('test_mode', None),
            base_currency=dictionary['base_currency']['selected'],
            base_symbol=dictionary['base_symbol']['selected'],
            savings_plan_cost=dictionary['savings_plan']['cost'],
            savings_plan_interval=dictionary['savings_plan']['interval']['selected'],
            savings_plan_execution_time=dictionary['savings_plan']['execution_time'],
            savings_plan_automatic_execution=dictionary['savings_plan']['automatic_execution'],
            portfolio_mode=dictionary['portfolio']['mode']['selected'],
            portfolio_weighting=dictionary['portfolio']['weighting']['selected'],
            cherry_pick_symbols=dictionary['portfolio'].get('cherry_pick', {}).get('symbols', None),
            custom_weights=dictionary['portfolio']['weighting'].get('custom', None),
            index_top_n=dictionary['portfolio'].get('index', {}).get('top_n', None),
            index_exclude_symbols=dictionary['portfolio'].get('index', {}).get('exclude_symbols', None)
        )
        return self


class TelegramBotConfig(BaseConfig):
    # no config needed yet
    @classmethod
    def from_config_yaml(cls, file_path):
        self = cls()
        return self


class SecretsStore(BaseConfig):
    binance_test: ExchangeToken
    kraken_test: ExchangeToken
    binance: ExchangeToken
    kraken: ExchangeToken
    coinbasepro: ExchangeToken
    telegram: TelegramToken
    dashboard_user: str
    dashboard_password: str

    @classmethod
    def from_secrets_yaml(cls, file_path):
        file = Path(file_path)
        with open(file) as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                logger.error("Error while parsing secrets file:")
                logger.error(exc)
                raise exc
        self = cls.from_dict(data)
        return self

    @classmethod
    def from_dict(cls, dictionary):
        self = cls(
            binance_test=ExchangeToken(
                exchange=ExchangeEnum.binance,
                api_key=dictionary['exchanges']['testnet']['binance']['api_key'],
                secret=dictionary['exchanges']['testnet']['binance']['secret']
            ),
            kraken_test=ExchangeToken(
                exchange=ExchangeEnum.kraken,
                api_key=dictionary['exchanges']['testnet']['kraken']['api_key'],
                secret=dictionary['exchanges']['testnet']['kraken']['secret']
            ),
            binance=ExchangeToken(
                exchange=ExchangeEnum.binance,
                api_key=dictionary['exchanges']['mainnet']['binance']['api_key'],
                secret=dictionary['exchanges']['mainnet']['binance']['secret']
            ),
            kraken=ExchangeToken(
                exchange=ExchangeEnum.kraken,
                api_key=dictionary['exchanges']['mainnet']['kraken']['api_key'],
                secret=dictionary['exchanges']['mainnet']['kraken']['secret']
            ),
            coinbasepro=ExchangeToken(
                exchange=ExchangeEnum.coinbasepro,
                api_key=dictionary['exchanges']['mainnet']['coinbasepro']['api_key'],
                secret=dictionary['exchanges']['mainnet']['coinbasepro']['secret'],
                passphrase=dictionary['exchanges']['mainnet']['coinbasepro']['passphrase']
            ),
            telegram=TelegramToken(
                token=dictionary['telegram']['token'],
                chat_id=dictionary['telegram']['chat_id']
            ),
            dashboard_user=dictionary['dashboard']['user'],
            dashboard_password=dictionary['dashboard']['password']
        )
        return self

    def get_exchange_tokens(self, test_mode: bool) -> [ExchangeToken]:
        if test_mode:
            return [self.binance_test, self.kraken_test]
        else:
            return [self.binance, self.kraken, self.coinbasepro]


class Config(BaseModel):
    trading_bot_config: TradingBotConfig
    telegram_bot_config: TelegramBotConfig
    dashboard_config: DashboardConfig
    secrets: SecretsStore

    @classmethod
    def from_yaml_files(cls, config_yaml='config.yaml', secrets_yaml='secrets.yaml'):
        self = cls(
            trading_bot_config=TradingBotConfig.from_config_yaml(file_path=config_yaml),
            telegram_bot_config=TelegramBotConfig.from_config_yaml(file_path=config_yaml),
            dashboard_config=DashboardConfig.from_config_yaml(file_path=config_yaml),
            secrets=SecretsStore.from_secrets_yaml(file_path=secrets_yaml)
        )
        return self

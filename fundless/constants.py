from typing import Final
import secrets


FIAT_SYMBOLS: Final = ['EUR', 'USD', 'GBP']
USD_COINS: Final = ['TUSD', 'USDC', 'BUSD', 'DAI', 'UST']
USD_SYMBOLS: Final = ['USD', 'TUSD', 'USDC', 'BUSD', 'DAI', 'UST']

EXCHANGE_REGEX: Final = '^(kraken|binance|coinbasepro)$'

# key: old symbol
# value: new symbol
COIN_REBRANDING: Final = {
    'NANO': 'XNO'
}

COIN_SYNONYMS: Final = [
    ['NANO', 'XNO']
]


class Auth0EnvNames:
    """ Constants for Auth0
    """
    AUTH0_CLIENT_ID = 'AUTH0_CLIENT_ID'
    AUTH0_CLIENT_SECRET = 'AUTH0_CLIENT_SECRET'
    AUTH0_CALLBACK_URL = 'AUTH0_CALLBACK_URL'
    AUTH0_DOMAIN = 'AUTH0_DOMAIN'
    AUTH0_AUDIENCE = 'AUTH0_AUDIENCE'
    PROFILE_KEY = 'profile'
    SECRET_KEY = secrets.token_hex(24)
    JWT_PAYLOAD = 'jwt_payload'
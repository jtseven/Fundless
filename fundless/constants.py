import secrets


FIAT_SYMBOLS = ['EUR', 'USD', 'GBP', 'ETH2']
USD_COINS = ['TUSD', 'USDC', 'BUSD', 'DAI', 'UST']
USD_SYMBOLS = ['USD', 'TUSD', 'USDC', 'BUSD', 'DAI', 'UST']

EXCHANGE_REGEX = '^(kraken|binance|coinbasepro)$'

# key: old symbol
# value: new symbol
COIN_REBRANDING = {
    'NANO': 'XNO'
}

COIN_SYNONYMS = [
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
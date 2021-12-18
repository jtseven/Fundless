from typing import Final

FIAT_SYMBOLS: Final = ['EUR', 'USD', 'GBP']
USD_COINS: Final = ['TUSD', 'USDC', 'BUSD', 'DAI', 'UST']
USD_SYMBOLS: Final = ['USD', 'TUSD', 'USDC', 'BUSD', 'DAI', 'UST']

EXCHANGE_REGEX: Final = '^(kraken|binance|coinbasepro)$'

COIN_REBRANDING: Final = {
    'NANO': 'XNO'
}
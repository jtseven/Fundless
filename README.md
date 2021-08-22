# FundLess
A crypto currency trading bot, that is aiming at a buy and hold strategy with marketcap weighted index-like portfolio and recurrent buys.

Interaction with the bot is done by Telegram, analytics on the bots performance is available via a web-based dashboard.

### Telegram Interface
<img src="doc/screenshot_telegram.jpeg" width="300" />

### Dashboard
<img src="doc/screenshot_dashboard.png" width="900" />


## Get Started
To get started you need to:
- create an API key on your favorite exchange
- talk to [BotFather](https://core.telegram.org/bots#6-botfather), to create your own Telegram bot
- get your personal telegram chat-id:
    1. just search for `@chatid_echo_bot` on telegram and type `/start`. It will echo your chat id
  
1. Copy the example files
    * `cp config.yaml_example config.yaml`
    * `cp secrets.yaml_example secrets.yaml`
2. Add your exchange API keys, your Telegram bot token and your personal telegram chat id to `secrets.yaml`
3. Edit the `config.yaml` as you desire. The example config is configured to run with the Binance testnet API. You get some free test funds to play around with, when you create a [Binance testnet](https://testnet.binance.vision/) API key.
4. Run FundLess
    * **Pure Python:** Install the requirements from `requirements.txt` and run `main.py` from the projects root directory (`python3 fundless/main.py`)
    * **Docker** Run `docker-compose up` in the project directory.
      * If you want to leave FundLess running in the background, run `docker-compose up -d`

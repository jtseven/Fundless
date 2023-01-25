import time
import requests.exceptions
from utils import print_crypto_amount
import ccxt
import telegram.error
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    CallbackContext,
    TypeHandler,
    Application,
    ContextTypes,
)
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    User,
    Chat,
)
from telegram.constants import ChatAction
import logging
from typing import Awaitable, Callable, Any
from trading import TradingBot
from config import Config
import sys
from redo import retriable
from random import randint

logger = logging.getLogger(__name__)


class StateChangeUpdate(Update):
    # An empty update that is used to trigger a state change for the conversation handler
    # The new state must be set within `context.bot_data["new_state"]` first

    def __init__(self, **_kwargs: Any):
        super().__init__(randint(0, 999999999), **_kwargs)


# Decorator to check if message is from authorized sender
def authorized_only(command_handler: Callable[..., Awaitable]) -> Callable[..., Any]:
    async def wrapper(self, *args, **kwargs):
        update = kwargs.get("update") or args[0]
        chat_id = int(self.chat_id)
        if int(update.message.chat_id) != chat_id:
            logger.info(f"Rejected unauthorized message from: {update.message.chat_id}")
            await update.message.reply_text("Sorry, you are not authorized, to use this bot!")
            await update.message.reply_text("Initiating self destruction...")
            return wrapper

        logger.info("Executing handler: %s for chat_id: %s", command_handler.__name__, chat_id)
        try:
            return await command_handler(self, *args, **kwargs)
        except Exception as e:
            logger.exception("Exception occurred within Telegram Bot")
            raise e

    return wrapper


# Define states that a conversation can have
REBALANCING_DECISION, PLANNING, EXECUTING, CHECKING = range(4)


class TelegramBot:
    def __init__(self, config: Config, trading_bot: TradingBot):
        self.secrets = config.secrets.telegram
        self.command_keyboard = [
            [KeyboardButton(r"/savings_plan"), KeyboardButton(r"/config")],
            [KeyboardButton(r"/balance"), KeyboardButton(r"/index")],
            [KeyboardButton(r"/performance"), KeyboardButton(r"/allocation")],
            [KeyboardButton(r"/cancel")],
        ]
        self.chat_id = self.secrets["chat_id"]
        self.trading_bot = trading_bot
        self.config = config
        self.rebalance = config.trading_bot_config.savings_plan_rebalance_on_automatic_execution
        self.order_weights = None
        self.order_symbols = None

        self.UnknownAnswerHandler = MessageHandler(filters.TEXT & ~filters.COMMAND, self._unknown)

        self.savings_plan_conversation = ConversationHandler(
            entry_points=[CommandHandler("savings_plan", self._rebalancing_question)],
            states={
                REBALANCING_DECISION: [MessageHandler(filters.Regex("^(Yes|No)$"), self._rebalancing_decision)],
                PLANNING: [MessageHandler(filters.Regex("^(Yes|No)$"), self._order_planning_conversation)],
                EXECUTING: [
                    MessageHandler(
                        filters.Regex("^(Yes|No)$"),
                        self._savings_plan_execution_conversation,
                    )
                ],
                CHECKING: [
                    TypeHandler(StateChangeUpdate, self._change_conversation_state),
                    MessageHandler(filters.TEXT | filters.COMMAND, self._executing_answer),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", self._cancel),
                self.UnknownAnswerHandler,
            ],
        )

        self.handles = [
            self.savings_plan_conversation,
            CommandHandler("start", self._start),
            CommandHandler("balance", self._balance),
            CommandHandler("index", self._index),
            CommandHandler("performance", self._performance),
            CommandHandler("allocation", self._allocation),
            CommandHandler("config", self._config),
            CommandHandler("cancel", self._cancel),
            MessageHandler(filters.COMMAND, self._unknown_command),
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._hodl_answer),
        ]
        self.application = Application.builder().token(self.secrets["token"]).build()

        for handle in self.handles:
            self.application.add_handler(handle)
        self.application.add_error_handler(self._error)

    async def run_polling(self):
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

    @staticmethod
    async def _error(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Log Errors caused by Updates."""
        logger.error(f"ERROR: '{context.error}' caused by '{update}'")

    @authorized_only
    async def _config(self, update: Update, _: CallbackContext):
        msg = self.trading_bot.bot_config.trading_bot_config.print_markdown()
        await update.message.reply_text("This is your current config:")
        await update.message.reply_text(msg, parse_mode="MarkdownV2")

    @authorized_only
    async def _performance(self, update: Update, context: CallbackContext):
        await context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)

        invested = self.trading_bot.analytics.invested
        balance = (await self.trading_bot.analytics.index_balance())[2].sum()
        performance = self.trading_bot.analytics.performance

        chart = self.trading_bot.analytics.value_history_chart(as_image=True)

        if balance - invested > 0:
            pl = "Profit"
        else:
            pl = "Loss"
        msg = "```\n"
        msg += "----- Performance Report: -----\n"
        msg += f"\tInvested amount:\t{invested:7.2f} {self.config.trading_bot_config.base_currency.values[1]}\n"
        msg += f"\tPortfolio value:\t{balance:7.2f} {self.config.trading_bot_config.base_currency.values[1]}\n"
        msg += f"\tPerformance:\t\t\t\t\t{performance:.2%}\n"
        msg += f"\t{pl}:\t\t\t\t\t\t\t\t\t\t{balance-invested:.2f} {self.config.trading_bot_config.base_currency.values[1]}\n"
        msg += "-------------------------------"
        msg += "```"

        await context.bot.send_photo(chat_id=self.chat_id, photo=chart)
        await update.message.reply_text(msg, parse_mode="MarkdownV2")

    @authorized_only
    async def _allocation(self, _: Update, context: CallbackContext):
        allocation_pie_chart = self.trading_bot.analytics.allocation_pie(as_image=True)
        await context.bot.send_photo(chat_id=self.chat_id, photo=allocation_pie_chart)

    @authorized_only
    async def _start(self, _: Update, context: CallbackContext):
        await context.bot.send_message(chat_id=self.chat_id, text="I'm FundLess, please talk to me!")

    @retriable(attempts=5, sleeptime=4, retry_exceptions=(telegram.error.NetworkError,))
    @authorized_only
    async def _balance(self, _: Update, context: CallbackContext) -> None:
        await context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
        try:
            symbols, amounts, values, allocations = self.trading_bot.balance()
        except ccxt.BaseError as e:
            msg = "I had a problem getting your balance from the exchange!"
            await context.bot.send_message(chat_id=self.chat_id, text=msg)
            await context.bot.send_message(chat_id=self.chat_id, text="That is, what the exchange returned:")
            await context.bot.send_message(chat_id=self.chat_id, text=str(e))
        except KeyError as e:
            await context.bot.send_message(
                chat_id=self.chat_id,
                text="Uh ohhh, I had a problem while computing your balances",
            )
            await context.bot.send_message(
                chat_id=self.chat_id,
                text=f"Could not find {e.args[0]} in market data of {self.trading_bot.bot_config.trading_bot_config.exchange.value}",
            )
        except requests.exceptions.HTTPError:
            await context.bot.send_message(
                chat_id=self.chat_id,
                text="I had network problems while computing your balance!",
            )
            await context.bot.send_message(chat_id=self.chat_id, text="The coingecko API limit might be reached.")
        else:
            msg = "```\n"
            msg += f"--- Your current balance on {self.trading_bot.exchanges.active.name}: ---\n"
            for symbol, allocation, value in zip(symbols, allocations, values):
                if value < 1.0:
                    continue
                msg += f" {symbol + ':': <6} {allocation:6.2f}% {value:10,.2f} {self.config.trading_bot_config.base_currency.values[1]}\n"
            msg += "-------------------------------\n"
            msg += (
                f"  Overall Balance: {values.sum():,.2f} {self.config.trading_bot_config.base_currency.values[1]}"
            )
            msg += "```"
            await context.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode="MarkdownV2")

    @retriable(attempts=5, sleeptime=4, retry_exceptions=(telegram.error.NetworkError,))
    @authorized_only
    async def _index(self, _: Update, context: CallbackContext) -> None:
        await context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
        try:
            (
                symbols,
                amounts,
                values,
                allocations,
            ) = await self.trading_bot.analytics.index_balance()
            symbols, index_weights = self.trading_bot.analytics.fetch_index_weights(symbols=symbols)
        except KeyError as e:
            await context.bot.send_message(
                chat_id=self.chat_id,
                text="Uh ohhh, I had a problem while computing your balances",
            )
            await context.bot.send_message(
                chat_id=self.chat_id,
                text=f"Could not find {e.args[0]} in market data of {self.trading_bot.bot_config.trading_bot_config.exchange.value}",
            )
        else:
            tracking_error = allocations - (index_weights * 100)
            msg = "```\n"
            msg += "Your current index portfolio:\n"
            msg += f"- Coin  Alloc  Value AllocErr -\n"
            for symbol, allocation, value, error in zip(symbols, allocations, values, tracking_error):
                msg += f"  {symbol.upper() + ':': <6} {allocation:4.1f}% {value:3,.0f} {self.config.trading_bot_config.base_currency.values[1]}  {error:4.1f}pp\n"
            msg += "-------------------------------\n"
            msg += (
                f"  Overall Balance: {values.sum():,.2f} {self.config.trading_bot_config.base_currency.values[1]}"
            )
            msg += "```"
            await context.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode="MarkdownV2")

    @retriable(attempts=5, sleeptime=4, retry_exceptions=(telegram.error.NetworkError,))
    async def ask_savings_plan_execution(self):
        reply_keyboard = [[KeyboardButton(r"/savings_plan"), KeyboardButton(r"/cancel")]]
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
        msg = f"Should I execute your savings plan?"
        self.application.bot.send_message(chat_id=self.chat_id, text=msg, reply_markup=markup)
        msg = "If yes, enter /savings_plan"
        self.application.bot.send_message(chat_id=self.chat_id, text=msg, reply_markup=markup)

    async def order_planning(self, automatic: bool) -> bool:
        order_dict = await self.trading_bot.savings_plan_order_planner(self.rebalance)
        symbols = order_dict["symbols"]
        weights = order_dict["weights"]
        messages = order_dict["messages"]

        if len(messages) > 0:
            if self.config.telegram_bot_config.verbose_messages or not order_dict["executable"]:
                for msg in messages:
                    self.application.bot.send_message(chat_id=self.chat_id, text=msg)

        if not order_dict["executable"]:
            return False

        if self.config.telegram_bot_config.verbose_messages or not automatic:
            msg = "```\nThat's what I came up with:\n" "---------------------------"
            for symbol, weight in zip(symbols, weights):
                msg += f"\n  {symbol.upper() + ':': <6}  {weight * self.trading_bot.bot_config.trading_bot_config.savings_plan_cost:6.2f} {self.config.trading_bot_config.base_currency.values[1]}"
            msg += "\n---------------------------"
            msg += f"\n Sum:  {weights.sum() * self.trading_bot.bot_config.trading_bot_config.savings_plan_cost:.2f} {self.config.trading_bot_config.base_currency.values[1]}"
            msg += "\n```"
            logger.info(msg)
            await self.application.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode="MarkdownV2")
            base_amount = self.trading_bot.analytics.base_currency_to_base_symbol(
                self.config.trading_bot_config.savings_plan_cost
            )
            base_amount = print_crypto_amount(base_amount)
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=f"You are buying with {base_amount} {self.trading_bot.bot_config.trading_bot_config.base_symbol.upper()}",
            )
            await self.application.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)

        self.order_weights = weights
        self.order_symbols = symbols
        return True

    @retriable(attempts=5, sleeptime=4, retry_exceptions=(telegram.error.NetworkError,))
    @authorized_only
    async def _order_planning_conversation(self, update: Update, context: CallbackContext):
        # TODO check if bot asked for execution before
        if update.message.text == "No":
            await update.message.reply_text("Okay, canceling this savings plan!")
            return ConversationHandler.END

        await update.message.reply_text("Alright! I am computing the optimal buy order...")
        await context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
        time.sleep(1)
        if not await self.order_planning(automatic=False):
            return ConversationHandler.END

        reply_keyboard = [["Yes", "No"]]
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(text="Should I proceed?", reply_markup=markup)

        return EXECUTING

    @authorized_only
    async def _rebalancing_question(self, update: Update, _: CallbackContext):
        await update.message.reply_text("Great!")
        await update.message.reply_text(
            f"Your order volume is {self.trading_bot.bot_config.trading_bot_config.savings_plan_cost:,.0f} {self.config.trading_bot_config.base_currency.values[1]}"
        )
        cost = self.trading_bot.analytics.base_currency_to_base_symbol(
            self.trading_bot.bot_config.trading_bot_config.savings_plan_cost
        )
        await update.message.reply_text(
            f"Buying with {print_crypto_amount(cost)}"
            + f" {self.trading_bot.analytics.get_coin_name(self.trading_bot.bot_config.trading_bot_config.base_symbol)}"
        )
        await update.message.reply_text("I will first check, if rebalancing of your portfolio is recommended...")

        allocation_error = await self.trading_bot.allocation_error()
        rel_to_volume = allocation_error["rel_to_order_volume"]
        if abs(rel_to_volume.max()) >= 0.10:
            symbol = allocation_error["symbols"][rel_to_volume.argmax()]
            coin_name = self.trading_bot.analytics.get_coin_name(symbol)
            err = abs(rel_to_volume.max())
            await update.message.reply_text(
                f"The absolute allocation error of {coin_name} is {err:.1%} of your order volume!"
            )

            reply_keyboard = [["Yes", "No"]]
            markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                "Would you like me to rebalance your portfolio with this savings plan execution?",
                reply_markup=markup,
            )
            await update.message.reply_text("I would recommend to execute rebalancing")
            return REBALANCING_DECISION
        else:
            await update.message.reply_text("Ahh perfect, your portfolio looks well balanced!")
            self.rebalance = False

            reply_keyboard = [["Yes", "No"]]
            markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                "Should I proceed with an overview of the planned buy order?",
                reply_markup=markup,
            )
            return PLANNING

    @authorized_only
    async def _rebalancing_decision(self, update: Update, context: CallbackContext):
        if update.message.text == "Yes":
            await update.message.reply_text("Alright, I will rebalance your portfolio with this order...")
            self.rebalance = True
        elif update.message.text == "No":
            await update.message.reply_text("Okay, no rebalancing this time...")
            self.rebalance = False
        reply_keyboard = [["Yes", "No"]]
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "Should I proceed with an overview of the planned buy order?",
            reply_markup=markup,
        )
        return PLANNING

    async def order_report(self, report):
        send = self.application.bot.send_message
        problems = report["problems"]
        if problems["fail"]:
            await send(chat_id=self.chat_id, text="I can not place your orders!")
            time.sleep(1)
            if len(problems["symbols"].keys()) > 0:
                msg = "Problematic coins:"
                for symbol in problems["symbols"].keys():
                    msg += f"\n\t- {symbol}, {problems['symbols'][symbol]}"
                await send(chat_id=self.chat_id, text=msg)
            else:
                await send(chat_id=self.chat_id, text=problems["description"])
            time.sleep(1)
            await send(chat_id=self.chat_id, text="Solve the problems and try again next time!")
            await send(chat_id=self.chat_id, text="See you")
            return ConversationHandler.END
        else:
            if "adjusted_volume" in problems:
                await send(
                    chat_id=self.chat_id,
                    text="The order amount was adjusted by a small amount, as your available balance was slightly lower than needed!",
                )
            order_ids = report["order_ids"]
            placed_symbols = report["symbols"]
            if self.config.telegram_bot_config.verbose_messages:
                await send(chat_id=self.chat_id, text="Done! I placed your orders")
                await send(
                    chat_id=self.chat_id,
                    text="I will check if your orders went threw in a few seconds and get back to you :)",
                )
            self.application.job_queue.run_once(self.check_orders, when=10, data=(order_ids, placed_symbols, 1))
            return CHECKING

    async def execute_order(self):
        try:
            await self.application.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
            report = self.trading_bot.weighted_buy_order(self.order_symbols, self.order_weights)
        except ccxt.BaseError as e:
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text="Ohhh, there was a Problem with the exchange! Sorry :(",
            )
            await self.application.bot.send_message(
                chat_id=self.chat_id, text="This is, what the exchange returned:"
            )
            await self.application.bot.send_message(chat_id=self.chat_id, text=str(e))
            await self.application.bot.send_message(
                chat_id=self.chat_id, text="Try to solve it and try again next time"
            )
            await self.application.bot.send_message(chat_id=self.chat_id, text="See you :)")
            return ConversationHandler.END
        return await self.order_report(report)

    @authorized_only
    async def _savings_plan_execution_conversation(self, update: Update, _: CallbackContext):
        if update.message.text == "Yes":
            await update.message.reply_text(
                f"Great! I am buying your crypto on {self.trading_bot.bot_config.trading_bot_config.exchange.values[1]}"
            )
            return await self.execute_order()
        else:
            await update.message.reply_text("Hmmm.. okay.. I will ask you another time")
            return ConversationHandler.END

    @authorized_only
    async def _executing_answer(self, update: Update, _: CallbackContext):
        await update.message.reply_text("Your order is being executed on the exchange, just relax for a while")
        await update.message.reply_text("I will get back to you shortly!")
        return CHECKING

    async def check_orders(self, context: CallbackContext):
        job = context.job
        order_ids, symbols, n_retry = job.data
        user = User(first_name="name", is_bot=False, id=self.chat_id)
        chat = Chat(id=self.chat_id, type="private")
        try:  # everything in try block, to correctly end conversation state in case of exception
            if self.config.telegram_bot_config.verbose_messages:
                await context.bot.send_message(self.chat_id, text="I am checking your orders now!")
                await context.bot.send_chat_action(self.chat_id, action=ChatAction.TYPING)
            order_report = self.trading_bot.check_orders(order_ids, symbols)
            open_orders = order_report["open"]
            closed_orders = order_report["closed"]
            missing = [symbol for symbol in symbols if symbol not in closed_orders + open_orders]
            if len(missing) > 0:
                await context.bot.send_message(
                    self.chat_id,
                    text="Oh ohh, I did not find all the orders I placed :0",
                )
                await context.bot.send_message(self.chat_id, text="Orders for those coins are missing:")
                msg = "```\n"
                for missing_symbol in missing:
                    msg += f"  - {missing_symbol.upper()}\n"
                msg += "```"
                await context.bot.send_message(self.chat_id, text=msg)

            if len(closed_orders) > 0:
                volume = 0.0
                msg = "```\n"
                msg += "----- Completed Coins -----"
                for symbol in closed_orders:
                    msg += (
                        f"\n  - {symbol.split('/')[0].upper()}  {order_report[symbol]['cost']:<6.2f} "
                        f"{self.config.trading_bot_config.base_currency.values[1]}"
                    )
                    volume += order_report[symbol]["cost"]
                msg += "\n---------------------------"
                base_currency_volume = self.trading_bot.analytics.base_symbol_to_base_currency(volume)
                msg += f"\n-- Filled Volume: {base_currency_volume:<4.0f} {self.config.trading_bot_config.base_currency.values[1]} --"
                msg += "\n```"
                await context.bot.send_message(self.chat_id, text=msg, parse_mode="MarkdownV2")

            if len(closed_orders) == len(order_ids):
                if self.config.telegram_bot_config.verbose_messages:
                    await context.bot.send_message(self.chat_id, text="Nice, all your orders are filled!")
                    await context.bot.send_message(self.chat_id, text="See you :)")
                self.application.bot_data["next_state"] = ConversationHandler.END
                state_update = StateChangeUpdate()
                state_update._effective_user = user
                state_update._effective_chat = chat
                await context.update_queue.put(state_update)
            else:
                await context.bot.send_message(self.chat_id, text="Some of your orders are not filled yet:")
                msg = "```\n"
                for symbol in open_orders:
                    msg += f"  - {symbol.upper()}\n"
                msg += "```"
                await context.bot.send_message(self.chat_id, text=msg, parse_mode="MarkdownV2")
                if n_retry > 10:
                    logger.warning(
                        "Not all orders where filled, check manually and add filled orders to trades.csv!"
                    )
                    await context.bot.send_message(
                        self.chat_id,
                        text="We have waited long enough! Pls solve the orders that are" "still open manually..",
                    )
                    self.application.bot_data["next_state"] = ConversationHandler.END
                    state_update = StateChangeUpdate()
                    state_update._effective_user = user
                    state_update._effective_chat = chat
                    await context.update_queue.put(state_update)
                else:
                    wait_time = 60 * n_retry * n_retry  # have an exponentially increasing wait time
                    logger.warning(f"Orders will be checked again in {wait_time} seconds!")
                    await context.bot.send_message(
                        self.chat_id,
                        text=f"I will wait {wait_time / 60:.0f} minutes and get back to you :)",
                    )
                    context.job_queue.run_once(
                        self.check_orders,
                        when=wait_time,
                        data=(order_ids, symbols, n_retry + 1),
                    )
                    self.application.bot_data["next_state"] = CHECKING
                    state_update = StateChangeUpdate()
                    state_update._effective_user = user
                    state_update._effective_chat = chat
                    await context.update_queue.put(state_update)
        except Exception as e:
            self.application.bot_data["next_state"] = ConversationHandler.END
            state_update = StateChangeUpdate()
            state_update._effective_user = user
            state_update._effective_chat = chat
            logger.error(f"Uncaught error when checking order status!")
            logger.error(e)
            raise e

    async def _change_conversation_state(self, _: StateChangeUpdate, __: CallbackContext):
        next_state = self.application.bot_data.get("next_state", 42)
        if next_state == ConversationHandler.END:
            return ConversationHandler.END
        elif next_state == CHECKING:
            return CHECKING
        else:
            raise ValueError("Invalid state passed!")

    @authorized_only
    async def _cancel(self, update: Update, _: CallbackContext) -> int:
        user = update.message.from_user
        logger.info("User %s canceled the conversation.", user.first_name)
        await update.message.reply_text(
            "Bye! I hope we can talk again some day.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    @authorized_only
    async def _hodl_answer(self, update: Update, context: CallbackContext) -> None:
        markup = ReplyKeyboardMarkup(self.command_keyboard, resize_keyboard=True, one_time_keyboard=True)
        await context.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)
        time.sleep(1)
        await update.message.reply_text("HODL!", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("You can use the following commands:", reply_markup=markup)
        await update.message.reply_text(
            "/savings_plan\n/config\n/balance\n/index\n/performance\n/allocation\n/cancel",
            reply_markup=markup,
        )

    @authorized_only
    async def _unknown(self, _: Update, context: CallbackContext):
        await context.bot.send_message(chat_id=self.chat_id, text="Sorry, I didn't understand that.")
        reply_keyboard = [["Yes", "No", "/cancel"]]
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
        await context.bot.send_message(
            chat_id=self.chat_id,
            text="Would you like to proceed or cancel?",
            reply_markup=markup,
        )

    @authorized_only
    async def _unknown_command(self, _: Update, context: CallbackContext):
        await context.bot.send_message(chat_id=self.chat_id, text="Sorry, I do not know that command.")
        markup = ReplyKeyboardMarkup(self.command_keyboard, resize_keyboard=True, one_time_keyboard=True)
        await context.bot.send_message(
            chat_id=self.chat_id,
            text="You can use these commands:",
            reply_markup=markup,
        )

    async def send(self, text: str):
        await self.application.bot.send_message(chat_id=self.chat_id, text=text)

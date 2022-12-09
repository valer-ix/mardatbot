# -*- coding:utf-8 -*-
"""
Author: Valery Gusev
"""

import re
import os
from sys import path
from decimal import Decimal
import jwt
import pandas as pd
import plotly.graph_objects as go
import datetime
from functools import wraps

from configparser import ConfigParser

from telegram import ParseMode, ChatAction, Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
from telegram import InputMediaPhoto
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
from telegram.ext.dispatcher import run_async

from mdapi import DataStorage, MDApiConnector
from fundamental import FundamentalApi

import logging

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

config = ConfigParser()
config.read_file(open('config.ini'))

PORT = int(os.environ.get('PORT', 5000))
TOKEN = config['Telegram']['token']

up = Updater(token=TOKEN, workers=32, use_context=True)
dispatcher = up.dispatcher

api = MDApiConnector(
    client_id=config['API']['client_id'],
    app_id=config['API']['app_id'],
    key=config['API']['shared_key']
)
fapi = FundamentalApi()
storage = DataStorage(api)
storage.start()


def send_typing_action(func):
    @wraps(func)
    def command_func(update, context, *args, **kwargs):
        context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=ChatAction.TYPING)
        return func(update, context,  *args, **kwargs)
    return command_func


def build_menu(buttons, n_cols, header_buttons=None, footer_buttons=None):
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
    if header_buttons:
        menu.insert(0, [header_buttons])
    if footer_buttons:
        menu.append([footer_buttons])
    return menu


def show_tchart_keyboard(instrum_type):
    data = [InlineKeyboardButton("Show Chart", callback_data=f"{instrum_type}")]
    return InlineKeyboardMarkup(build_menu(data, n_cols=1))


def tchart_keyboard():
    data = ["30 mins.", "1 hour", "6 hours", "1 day", "1 week", "30 days", "3 months", "6 months"]
    button_list = []
    for each in data:
        button_list.append(InlineKeyboardButton(each, callback_data=each))
    return InlineKeyboardMarkup(build_menu(button_list, n_cols=2))


def tchart_timestamp_dict(trange):
    data = {"30 mins.": 1800,
            "1 hour": 3600,
            "6 hours": 21600,
            "1 day": 86400,
            "1 week": 604800,
            "30 days": 2592000,
            "3 months": 7776000,
            "6 months": 15552000
            }
    return data[trange]


def start(update, context):
    msg = "Hello, {user_name}! I am {bot_name}. Ask me about stocks or currency exchange rates!\n\n" \
          "<b>— FOR STOCKS —</b>\n\t\t\t\t\tEnter a ticker code (e.g. <b><u>goog</u></b> for Google, " \
          "<b><u>aapl</u></b> for Apple, etc.) to retrieve " \
          "an instrument's price and historical data.\n\n" +\
          "<b>— FOR EXCHANGE RATES —</b>\n\t\t\t\t\tEnter a currency code pair in the form of " \
          "<b><u>abc/xyz</u></b> — e.g. <b><u>eur/usd</u></b>, <b><u>rub/eur</u></b> or <b><u>gbp/jpy</u></b>.\n\n" \
          "<b>— FOR CRYPTOCURRENCIES —</b>\n\t\t\t\t\tEnter a ticker code to retrieve an instrument's " \
          "price and historical data." \
          "\n\n<b><u>/help</u></b> — See this message again.\n" \
          "<b><u>/cryptolist</u></b> — List of available cryptocurrencies (ticker codes in brackets).\n"

    context.bot.send_message(chat_id=update.message.chat_id,
                             text=msg.format(
                                 user_name=update.message.from_user.first_name,
                                 bot_name=context.bot.name),
                             # entities=MessageEntity(type="bot_command", offset=0, length=20),
                             parse_mode="html")


@send_typing_action
@run_async
def process(update, context):
    stock, crossrate, crypto, base, counter = None, None, None, None, None

    ticker_cr = re.search(r'([\w]{1,4})/([\w]{1,4})', update.message.text)
    if ticker_cr:
        base = ticker_cr.group(1).upper()
        counter = ticker_cr.group(2).upper()
        crossrate = storage.crossrates.get(base + "/" + counter)

        if not crossrate:
            base, counter = counter, base
            crossrate = storage.crossrates.get(base + "/" + counter)
    else:
        ticker = re.search(r'[\w]{1,9}', update.message.text)
        if ticker:
            ticker = ticker.group(0).upper()
            stock = storage.stocks.get(ticker)
            crypto = storage.crypto.get(ticker)

    if crossrate:
        print(crossrate)
        crossrate["id"] = re.sub(r"/", r"%2F", crossrate["id"])
        price = round(Decimal(api.get_crossrate_price(base, counter)), 4)
        if crossrate["id"] in storage.feed:
            feed = storage.feed[crossrate["id"]]
        else:
            feed = api.get_feed(crossrate["id"])[0]
            feed["symbolId"] = re.sub(r"/", r"%2F", feed["symbolId"])
            storage.feed[crossrate["id"]] = feed
        timestamp = pd.to_datetime(feed["timestamp"], unit="ms").strftime("%b %d, %H:%M:%S")
        bid, ask = "N/A", "N/A"
        if len(feed["bid"]) != 0:
            bid = round(Decimal(feed["bid"][0]["value"]), 4)
        if len(feed["ask"]) != 0:
            ask = round(Decimal(feed["ask"][0]["value"]), 4)

        msg = f"<b>{crossrate['description']} ({crossrate['ticker']}, {crossrate['exchange']}):</b>\n\n" \
              f"Current Price:  <b><u>{price} {counter}</u></b>\n" \
              f"—> [Bid <b>{bid} {counter}</b>]\n" \
              f"—> [Ask <b>{ask} {counter}</b>]\n" \
              f"<em>Last updated at {timestamp} UTC</em>\n"

        context.user_data['user_input_cross'] = [crossrate, None]
        context.user_data['counter_currency'] = counter
        if context.user_data["user_input_cross"][1] is not None:
            context.bot.delete_message(chat_id=update.message.chat_id,
                                       message_id=context.user_data["user_input_cross"][1])
            context.user_data["user_input_cross"][1] = None
        update.message.reply_text(text=msg, reply_markup=show_tchart_keyboard("cross"), parse_mode="html")

    if stock:
        print(stock)
        stock["id"] = re.sub(r"/", r"%2F", stock["id"])
        price = api.get_last_ohlc_bar(stock['id'])

        key_metrics = fapi.request(stock["ticker"], "key-metrics")
        ratios = fapi.request(stock["ticker"], "ratios")
        inc_stmnt = fapi.request(stock["ticker"], "income-statement")

        d2e = "N/A"
        roe = "N/A"
        pe_ratio = "N/A"
        eps = "N/A"
        if type(inc_stmnt) == dict:
            msg = "<b>[Financial Modelling Prep API]:</b> Limit reached. Accounting ratios will not be retrieved."
            update.message.reply_text(text=msg, parse_mode="html")
        else:
            d2e = round(key_metrics[0]["debtToEquity"], 4)
            roe = round(ratios[0]["returnOnEquity"], 4)
            eps = 0
            for q in inc_stmnt:
                eps += q.get('epsdiluted')
            if Decimal(eps) != 0:
                if stock["currency"] != "USD":
                    pe_ratio = round(Decimal(key_metrics[0]["peRatio"]), 2)
                else:
                    pe_ratio = round(Decimal(price['close']) / Decimal(eps), 2)
                eps = round(Decimal(eps), 2)
                eps = f"{eps} {stock['currency']}"
            else:
                eps = "N/A"

        if stock["id"] in storage.feed:
            feed = storage.feed[stock["id"]]
        else:
            feed = api.get_feed(stock["id"])[0]
            storage.feed[stock["id"]] = feed
        timestamp = pd.to_datetime(feed["timestamp"], unit="ms").strftime("%b %d, %H:%M:%S")
        bid, ask = "N/A", "N/A"
        if len(feed["bid"]) != 0:
            bid = round(Decimal(feed["bid"][0]["value"]), 4)
        if len(feed["ask"]) != 0:
            ask = round(Decimal(feed["ask"][0]["value"]), 4)

        msg = f"<b>{stock['ticker']} ({stock['description']}, {stock['exchange']}):</b>\n\n" \
              f"Earnings per Share (TTM):  <b><u>{eps}</u></b>\n" \
              f"Price/Earnings (P/E) Ratio:  <b><u>{pe_ratio}</u></b>\n" \
              f"Debt/Equity (D/E) Ratio:  <b><u>{d2e}</u></b>\n" \
              f"Return on Equity:  <b><u>{roe}</u></b>\n\n" \
              f"Share Price:  <b><u>{round(Decimal(price['close']), 4)} {stock['currency']}</u></b>\n" \
              f"—> [Bid <b>{bid} {stock['currency']}</b>]\n" \
              f"—> [Ask <b>{ask} {stock['currency']}</b>]\n" \
              f"<em>Last updated at {timestamp} UTC</em>\n"

        context.user_data['user_input_stock'] = [stock, None]
        context.user_data['counter_currency'] = stock["currency"]
        if context.user_data["user_input_stock"][1] is not None:
            context.bot.delete_message(chat_id=update.message.chat_id,
                                       message_id=context.user_data["user_input_cross"][1])
            context.user_data["user_input_stock"][1] = None
        update.message.reply_text(text=msg, reply_markup=show_tchart_keyboard("stock"), parse_mode="html")

    if crypto:
        print(crypto)
        price = api.get_last_ohlc_bar(crypto['id'])
        if crypto["id"] in storage.feed:
            feed = storage.feed[crypto["id"]]
        else:
            feed = api.get_feed(crypto["id"])[0]
            storage.feed[crypto["id"]] = feed
        timestamp = pd.to_datetime(feed["timestamp"], unit="ms").strftime("%b %d, %H:%M:%S")
        bid, ask = "N/A", "N/A"
        if len(feed["bid"]) != 0:
            bid = round(Decimal(feed["bid"][0]["value"]), 4)
        if len(feed["ask"]) != 0:
            ask = round(Decimal(feed["ask"][0]["value"]), 4)

        msg = f"<b>{crypto['description']} ({crypto['ticker']}, {crypto['exchange']}):</b>\n\n" \
              f"Current Price:  <b><u>{round(Decimal(price['close']), 4)} {crypto['currency']}</u></b>\n" \
              f"—> [Buy <b>{bid} {crypto['currency']}</b>]\n" \
              f"—> [Sell <b>{ask} {crypto['currency']}</b>]\n" \
              f"<em>Last updated at {timestamp} UTC</em>\n"

        context.user_data['user_input_crypto'] = [crypto, None]
        context.user_data['counter_currency'] = crypto["currency"]
        if context.user_data["user_input_crypto"][1] is not None:
            context.bot.delete_message(chat_id=update.message.chat_id,
                                       message_id=context.user_data["user_input_cross"][1])
            context.user_data["user_input_crypto"][1] = None
        update.message.reply_text(text=msg, reply_markup=show_tchart_keyboard("crypto"), parse_mode="html")

    if all(v is None for v in [crossrate, stock, crypto]):
        msg = "Ticker label not recognised!\n" + \
              "Try asking about something else, like <b><u>GOOG</u></b>, <b><u>AMZN</u></b> or <b><u>AAPL</u></b>."
        update.message.reply_text(text=msg, parse_mode="html")


@send_typing_action
def tchart_menu(update, context):
    load_msg = None
    query = update.callback_query
    trange = query.data
    if query.data in ["cross", "stock", "crypto"]:
        context.user_data['look_at'] = query.data
        trange = "1 day"
    instrum_data = context.user_data[f"user_input_{context.user_data['look_at']}"]
    instrum = instrum_data[0]
    counter = context.user_data['counter_currency']
    if instrum_data[1] is None:
        load_msg = context.bot.send_message(text="...One moment, please!", chat_id=query.message.chat_id)
    else:
        context.bot.edit_message_caption(caption="...One moment, please!", chat_id=query.message.chat_id,
                                         message_id=query.message.message_id)

    df_ohlc = pd.DataFrame.from_records(api.get_ohlc(instrum['id'], trange))
    df_ohlc["timestamp"] = pd.to_datetime(df_ohlc["timestamp"], unit="ms")
    cutoff = df_ohlc["timestamp"][0] - datetime.timedelta(seconds=tchart_timestamp_dict(trange))
    df_ohlc["timestamp"] = df_ohlc["timestamp"].loc[df_ohlc["timestamp"] > cutoff]

    fig = go.Figure(data=[go.Candlestick(x=df_ohlc["timestamp"],
                                         open=df_ohlc["open"],
                                         high=df_ohlc["high"],
                                         low=df_ohlc["low"],
                                         close=df_ohlc["close"])],
                    layout=go.Layout(
                        title=go.layout.Title(text=f"{instrum['ticker']} {instrum['exchange']}, {trange}")
                    ))
    fig.update_xaxes(title_text="Date/Time (UTC+00:00)")
    fig.update_yaxes(title_text=counter)
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        autosize=False,
        width=1200,
        height=900,
        font_size=20
    )
    query.answer()
    fig.write_image("candlestick.png")
    if instrum_data[1] is None:
        context.bot.delete_message(chat_id=query.message.chat_id, message_id=load_msg.message_id)
        context.bot.send_photo(chat_id=query.message.chat_id, disable_notification=True,
                               caption='Choose the time range:', parse_mode="MarkdownV2",
                               photo=open("candlestick.png", "rb"), reply_markup=tchart_keyboard())
    else:
        context.bot.edit_message_media(media=InputMediaPhoto(open("candlestick.png", "rb")),
                                       parse_mode="MarkdownV2",
                                       chat_id=query.message.chat_id, message_id=query.message.message_id)
        context.bot.edit_message_caption(caption="Choose the time range:", chat_id=query.message.chat_id,
                                         message_id=query.message.message_id, reply_markup=tchart_keyboard())

    instrum_data[1] = query.message.message_id


@run_async
def cryptolist(update, context):
    msg = ""
    for x in storage.crypto:
        msg += f"{storage.crypto[x]['description']} | (<b><u>{x}</u></b>)\n"

    context.bot.send_message(chat_id=update.message.chat_id,
                             text=msg.format(
                                 user_name=update.message.from_user.first_name,
                                 bot_name=context.bot.name),
                             parse_mode="html")


if __name__ == "__main__":
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", start))
    dispatcher.add_handler(CommandHandler("cryptolist", cryptolist))
    dispatcher.add_handler(CallbackQueryHandler(tchart_menu))
    dispatcher.add_handler(MessageHandler(Filters.text, process))

    # up.start_webhook(listen="0.0.0.0",
                    #  port=int(PORT),
                    #  url_path=TOKEN)
    # up.bot.setWebhook('https://mardatbot.herokuapp.com/' + TOKEN)
    up.start_polling()
    up.idle()

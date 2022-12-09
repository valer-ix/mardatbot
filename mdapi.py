# -*- coding:utf-8 -*-

import time
from threading import Thread
from datetime import datetime

import jwt
import requests
import re

import logging

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

# token expiration time in seconds
EXPIRATION = 3600
API_URL = "https://api-demo.exante.eu/md/2.0"


class MDApiConnector:
    token = (None, None)
    algo = "HS256"
    __headers = {'accept': 'application/x-json-stream'}

    def __init__(self, client_id, app_id, key):
        self.client_id = client_id
        self.app_id = app_id
        self.key = key

    def __get_token(self):
        now = datetime.now()

        # if there is token and it's not expired yet
        if self.token[0] and (now - self.token[1]).total_seconds() < EXPIRATION:
            return self.token[0]

        claims = {
            "iss": self.client_id,
            "sub": self.app_id,
            "aud": ["symbols", "ohlc", "feed", "change", "crossrates",
                    "orders", "accounts", "summary", "transactions"],
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + EXPIRATION
        }

        new_token = str(jwt.encode(claims, self.key, self.algo), 'utf-8')
        self.token = (new_token, now)

        return new_token

    def __request(self, endpoint, params=None):
        token = self.__get_token()
        result = requests.get(API_URL + endpoint,
                              headers={"Authorization": f"Bearer {token}"},
                              params=params)
        result.raise_for_status()
        return result.json()

    def get_stocks(self):
        stocks = self.__request("/types/STOCK")
        return {x['ticker']: {"id": x["id"], "exchange": x["exchange"], "currency": x["currency"],
                              "description": x["description"], "country": x["country"], "ticker": x['ticker']}
                for ind, x in enumerate(stocks)}

    def get_crossrates(self):
        crossrates = self.__request("/types/CURRENCY")
        return {x['ticker']: {"id": x["id"], "ticker": x['ticker'], "exchange": x["exchange"],
                              "description": x["description"]}
                for x in crossrates}

    def get_crypto(self):
        crypto = self.__request("/types/FUND")
        crypto = {x['description']: {"id": x["id"], "ticker": x['ticker'], "exchange": x["exchange"], "name": x["name"],
                                     "description": x["description"], "currency": x["currency"]}
                  for x in crypto}
        crypto = dict(sorted(crypto.items()))
        return {crypto[x]['ticker']: {"id": crypto[x]["id"], "ticker": crypto[x]['ticker'],
                                      "exchange": crypto[x]["exchange"], "name": crypto[x]["name"],
                                      "description": crypto[x]["description"], "currency": crypto[x]["currency"]}
                for x in crypto}

    def get_crossrate_price(self, id1, id2):
        crossrate = self.__request(f"/crossrates/{id1}/{id2}")
        return crossrate["rate"]

    def get_last_ohlc_bar(self, symbol_id):
        ohlc = self.__request(f"/ohlc/{symbol_id}/86400", {"size": 1})
        return ohlc[0]

    def get_ohlc(self, symbol_id, duration):
        duration_dict = {"30 mins.": {"secs": 60, "cand": 30},
                         "1 hour": {"secs": 60, "cand": 60},
                         "6 hours": {"secs": 600, "cand": 36},
                         "1 day": {"secs": 3600, "cand": 24},
                         "1 week": {"secs": 21600, "cand": 28},
                         "30 days": {"secs": 86400, "cand": 30},
                         "3 months": {"secs": 86400, "cand": 90},
                         "6 months": {"secs": 86400, "cand": 180},
                         }
        ohlc = self.__request(f"/ohlc/{symbol_id}/{int(duration_dict[duration]['secs'])}",
                              {"size": int(duration_dict[duration]['cand'])})
        return ohlc

    def get_feed(self, symbol_id):
        feed = self.__request(f"/feed/{symbol_id}/last")
        return feed


class DataStorage(Thread):
    def __init__(self, connector):
        super().__init__()
        self.connector = connector
        self.stocks = {}
        self.crossrates = {}
        self.crypto = {}
        self.feed = {}
        self.skip = True
        self.cheat_feed = ["GOOG.NASDAQ", "AAPL.NASDAQ", "TSLA.NASDAQ", "AMZN.NASDAQ", "NFLX.NASDAQ",
                           "EUR%2FUSD.EXANTE", "EUR%2FRUB.EXANTE", "USD%2FRUB.EXANTE", "GBP%2FUSD.EXANTE",
                           "EUR%2FGBP.EXANTE"]
        print("Loading...")
        for i in range(0, 2):
            feed = self.connector.get_feed(",".join(self.cheat_feed[i * 5:i * 5 + 5]))
            for quote in feed:
                quote["symbolId"] = re.sub("/", "%2F", quote["symbolId"])
                self.feed[quote["symbolId"]] = quote
        print("Ready.")

    def run(self):
        while True:
            timeout = 15 * 60
            try:
                self.stocks = self.connector.get_stocks()
                self.crossrates = self.connector.get_crossrates()
                self.crypto = self.connector.get_crypto()
                if datetime.today().weekday() not in (5, 6) and not self.skip:
                    print("Loading...")
                    self.cheat_feed = [self.feed[x]["symbolId"] for x in self.feed]
                    for i in range(0, len(self.feed), 5):
                        feed = self.connector.get_feed(",".join(self.cheat_feed[i:i+5]))
                        for quote in feed:
                            quote["symbolId"] = re.sub("/", "%2F", quote["symbolId"])
                            self.feed[quote["symbolId"]] = quote
                    print("Ready.")
                self.skip = False
            except Exception as e:
                logger.error(e)
                timeout = 15

            time.sleep(timeout)

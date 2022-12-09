# -*- coding:utf-8 -*-

from datetime import datetime
import requests


class FundamentalApi:
    def __init__(self):
        self.cache = {}

    def request(self, symbol, sheet):
        now = datetime.now()

        result = self.cache.get(symbol)
        if result:
            result = result.get(sheet)
            if result and (now - result[1]).days < 1:
                return result[0]

        params = {"period": "quarter",
                  "apikey": "xyz"}

        url = f"https://financialmodelingprep.com/api/v3/{sheet}/{symbol}"
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if data and type(data) == list:
            data = response.json()[0:4]
        self.cache[symbol] = {sheet: (data, now)}

        return self.cache[symbol][sheet][0]

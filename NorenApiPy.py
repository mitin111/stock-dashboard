# NorenApiPy.py
# Minimal drop-in Noren API client for ProStocks
# Place this file in your repo root or inside your package

import requests
import json
import websocket
import threading
import time
import logging

logging.basicConfig(level=logging.INFO)

class NorenApi:
    def __init__(self, host, websocket=None):
        self.host = host.rstrip("/")
        self.ws_url = websocket
        self.session = requests.Session()
        self.jkey = None
        self.uid = None
        self.ws = None
        self.subscriptions = set()
        self.on_open = None
        self.on_close = None
        self.on_error = None
        self.on_message = None

    # ---------------- REST -----------------
    def login(self, payload):
        """payload should contain uid, pwd, factor2, vc, api_key, imei"""
        url = f"{self.host}/QuickAuth"
        resp = self.session.post(url, data={"jData": json.dumps(payload), "jKey": ""})
        data = resp.json()
        if data.get("stat") == "Ok":
            self.jkey = data["susertoken"]
            self.uid = payload["uid"]
        return data

    def logout(self):
        url = f"{self.host}/Logout"
        jdata = {"uid": self.uid}
        return self.session.post(url, data={"jData": json.dumps(jdata), "jKey": self.jkey}).json()

    def place_order(self, jdata):
        url = f"{self.host}/PlaceOrder"
        return self.session.post(url, data={"jData": json.dumps(jdata), "jKey": self.jkey}).json()

    def cancel_order(self, jdata):
        url = f"{self.host}/CancelOrder"
        return self.session.post(url, data={"jData": json.dumps(jdata), "jKey": self.jkey}).json()

    def modify_order(self, jdata):
        url = f"{self.host}/ModifyOrder"
        return self.session.post(url, data={"jData": json.dumps(jdata), "jKey": self.jkey}).json()

    def order_book(self):
        url = f"{self.host}/OrderBook"
        jdata = {"uid": self.uid}
        return self.session.post(url, data={"jData": json.dumps(jdata), "jKey": self.jkey}).json()

    def trade_book(self):
        url = f"{self.host}/TradeBook"
        jdata = {"uid": self.uid}
        return self.session.post(url, data={"jData": json.dumps(jdata), "jKey": self.jkey}).json()

    def tpseries(self, jdata):
        url = f"{self.host}/TPSeries"
        return self.session.post(url, data={"jData": json.dumps(jdata), "jKey": self.jkey}).json()

    # ---------------- WebSocket -----------------
    def _ws_on_open(self, ws):
        logging.info("WebSocket connected")
        if self.on_open:
            self.on_open(ws)

    def _ws_on_close(self, ws, *args):
        logging.info("WebSocket disconnected")
        if self.on_close:
            self.on_close(ws)

    def _ws_on_error(self, ws, error):
        logging.error(f"WebSocket error: {error}")
        if self.on_error:
            self.on_error(ws, error)

    def _ws_on_message(self, ws, msg):
        if self.on_message:
            self.on_message(ws, msg)

    def start_websocket(self):
        if not self.ws_url:
            raise ValueError("No WebSocket URL configured")
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=self._ws_on_open,
            on_close=self._ws_on_close,
            on_error=self._ws_on_error,
            on_message=self._ws_on_message,
        )
        wst = threading.Thread(target=self.ws.run_forever, daemon=True)
        wst.start()
        time.sleep(1)
        # auto auth
        if self.jkey:
            payload = {
                "t": "c",
                "uid": self.uid,
                "actid": self.uid,
                "susertoken": self.jkey,
                "source": "API",
            }
            self.ws.send(json.dumps(payload))

    def subscribe(self, tokens):
        if isinstance(tokens, str):
            tokens = [tokens]
        for t in tokens:
            self.subscriptions.add(t)
        req = {"t": "t", "k": ",".join(tokens)}
        self.ws.send(json.dumps(req))

    def unsubscribe(self, tokens):
        if isinstance(tokens, str):
            tokens = [tokens]
        for t in tokens:
            self.subscriptions.discard(t)
        req = {"t": "u", "k": ",".join(tokens)}
        self.ws.send(json.dumps(req))

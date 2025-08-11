
# prostocks_connector.py
import requests
import hashlib
import json
import os
import time
from dotenv import load_dotenv
from datetime import datetime
import threading
from websocket import WebSocketApp
import pandas as pd

load_dotenv()


class ProStocksAPI:
    def __init__(self, userid=None, password_plain=None, vc=None, api_key=None,
                 imei=None, base_url=None, apkversion="1.0.0"):
        self.userid = userid or os.getenv("PROSTOCKS_USER_ID")
        self.password_plain = password_plain or os.getenv("PROSTOCKS_PASSWORD")
        self.vc = vc or os.getenv("PROSTOCKS_VENDOR_CODE")
        self.api_key = api_key or os.getenv("PROSTOCKS_API_KEY")
        self.imei = imei or os.getenv("PROSTOCKS_MAC")
        self.base_url = (base_url or os.getenv("PROSTOCKS_BASE_URL")).rstrip("/")
        self.apkversion = apkversion
        self.session_token = None
        self.session = requests.Session()
        self.headers = {"Content-Type": "text/plain"}
        self.credentials = {
            "uid": self.userid,
            "pwd": self.password_plain,
            "vc": self.vc,
            "api_key": self.api_key,
            "imei": self.imei
        }

    def sha256(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    def send_otp(self):
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_hash = self.sha256(f"{self.userid}|{self.api_key}")
        payload = {
            "uid": self.userid, "pwd": pwd_hash, "factor2": "",
            "vc": self.vc, "appkey": appkey_hash, "imei": self.imei,
            "apkversion": self.apkversion, "source": "API"
        }
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            response = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"emsg": str(e)}

    def login(self, factor2_otp):
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_hash = self.sha256(f"{self.userid}|{self.api_key}")
        payload = {
            "uid": self.userid, "pwd": pwd_hash, "factor2": factor2_otp,
            "vc": self.vc, "appkey": appkey_hash, "imei": self.imei,
            "apkversion": self.apkversion, "source": "API"
        }
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            response = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("stat") == "Ok":
                    self.session_token = data["susertoken"]
                    self.userid = data["uid"]
                    self.headers["Authorization"] = self.session_token
                    return True, self.session_token
                else:
                    return False, data.get("emsg", "Unknown login error")
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"RequestException: {e}"

    def get_watchlists(self):
        return self._post_json(f"{self.base_url}/MWList", {"uid": self.userid})

    def get_watchlist(self, wlname):
        return self._post_json(f"{self.base_url}/MarketWatch", {"uid": self.userid, "wlname": wlname})

    def _post_json(self, url, payload):
        if not self.session_token:
            return {"stat": "Not_Ok", "emsg": "Not Logged In. Session Token Missing."}
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}&jKey={self.session_token}"
            response = self.session.post(url, data=raw_data, headers={"Content-Type": "text/plain"}, timeout=10)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"stat": "Not_Ok", "emsg": str(e)}


# --- TPSeries Helper ---
def fetch_tpseries(jkey, uid, exch, token, st_ts, et_ts, intrv='1', base_url="https://starapi.prostocks.com"):
    TPSERIES_PATH = "/NorenWClientTP/TPSeries"
    url = base_url.rstrip("/") + TPSERIES_PATH
    jdata = {
        "uid": uid, "exch": exch, "token": token,
        "st": int(st_ts), "et": int(et_ts), "intrv": str(intrv)
    }
    payload = {'jData': json.dumps(jdata), 'jKey': jkey}
    resp = requests.post(url, data=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get('stat') == 'Not_Ok':
        raise RuntimeError(f"TPSeries error: {data.get('emsg')}")
    return data


# --- Candle Utilities ---
def make_empty_candle(ts):
    return {'time': ts, 'open': None, 'high': None, 'low': None, 'close': None, 'volume': 0}

def update_candle_with_tick(candle, price, volume=0):
    if candle['open'] is None:
        candle['open'] = price
        candle['high'] = price
        candle['low'] = price
        candle['close'] = price
    else:
        candle['high'] = max(candle['high'], price)
        candle['low'] = min(candle['low'], price)
        candle['close'] = price
    candle['volume'] += int(volume or 0)


# --- WebSocket Client ---
class TickWebsocket:
    def __init__(self, ws_url, subscribe_tokens, on_tick_callback, headers=None):
        self.ws_url = ws_url
        self.subscribe_tokens = subscribe_tokens
        self.on_tick = on_tick_callback
        self.headers = headers or {}
        self.ws = None
        self.thread = None
        self.running = False

    def ws_on_open(self, ws):
        sub_msg = json.dumps({"action": "subscribe", "symbols": self.subscribe_tokens})
        ws.send(sub_msg)

    def ws_on_message(self, ws, message):
        try:
            msg = json.loads(message)
        except:
            return
        tick_price = None
        tick_volume = 0
        token = None
        if isinstance(msg, dict):
            if 'values' in msg and isinstance(msg['values'], list):
                item = msg['values'][0]
                tick_price = item.get('lp') or item.get('ltp')
                tick_volume = item.get('v', 0)
                token = item.get('token')
        if tick_price is None:
            return
        try:
            price = float(tick_price)
        except:
            return
        vol = int(tick_volume) if tick_volume else 0
        self.on_tick({'price': price, 'volume': vol, 'token': token, 'raw': msg, 'ts': time.time()})

    def start(self):
        self.running = True
        self.ws = WebSocketApp(
            self.ws_url,
            header=[f"{k}: {v}" for k, v in self.headers.items()],
            on_open=self.ws_on_open,
            on_message=self.ws_on_message
        )
        self.thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

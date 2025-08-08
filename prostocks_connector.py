
# prostocks_candle_builder.py

import requests
import hashlib
import json
import os
import time
from dotenv import load_dotenv
from datetime import datetime
import websocket
import threading
import pandas as pd

load_dotenv()

class ProStocksAPI:
    def __init__(self, userid=None, password_plain=None, vc=None, api_key=None, imei=None, base_url=None, apkversion="1.0.0"):
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

        self.ws = None
        self.ws_connected = False
        self.subscribed_tokens = []
        self.TIMEFRAMES = ["1min", "3min", "5min", "15min", "30min", "60min"]
        self.candles = {}
        self.candle_tokens = set()
        self.tick_data = {}
        self.candle_data = {}

    def sha256(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    def send_otp(self):
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_hash = self.sha256(f"{self.userid}|{self.api_key}")
        payload = {
            "uid": self.userid,
            "pwd": pwd_hash,
            "factor2": "",
            "vc": self.vc,
            "appkey": appkey_hash,
            "imei": self.imei,
            "apkversion": self.apkversion,
            "source": "API"
        }
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            response = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            print("\U0001f4e8 OTP Trigger Response:", response.text)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"emsg": str(e)}

    def login(self, factor2_otp):
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_hash = self.sha256(f"{self.userid}|{self.api_key}")
        payload = {
            "uid": self.userid,
            "pwd": pwd_hash,
            "factor2": factor2_otp,
            "vc": self.vc,
            "appkey": appkey_hash,
            "imei": self.imei,
            "apkversion": self.apkversion,
            "source": "API"
        }
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            response = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            print("\U0001f501 Login Response Code:", response.status_code)
            print("\U0001f4e8 Login Response Body:", response.text)
            if response.status_code == 200:
                data = response.json()
                if data.get("stat") == "Ok":
                    self.session_token = data["susertoken"]
                    self.userid = data["uid"]
                    self.headers["Authorization"] = self.session_token
                    print("\u2705 Login Success!")
                    return True, self.session_token
                else:
                    return False, data.get("emsg", "Unknown login error")
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"RequestException: {e}"

    def add_token_for_candles(self, token):
        print(f"\U0001fa9d Adding token to candle builder: {token}")
        self.candle_tokens.add(token)

        if self.ws_connected and self.ws:
            try:
                token_id = token.split("|")[1]
                payload = json.dumps({"t": "t", "k": [token_id]})
                self.ws.send(payload)
                print(f"\u2705 WebSocket subscription sent: {payload}")
            except Exception as e:
                print(f"\u274c Error sending subscription: {e}")
        else:
            print("\u26a0\ufe0f WebSocket not connected yet, token will subscribe on connect")

        self.start_candle_builder(list(self.candle_tokens))
        self.start_candle_builder_loop()

    def start_candle_builder_loop(self):
        def run():
            while True:
                for token in list(self.candle_tokens):
                    self.build_candles(token)
                time.sleep(10)
        threading.Thread(target=run, daemon=True).start()

    def start_candle_builder(self, token_list):
        if self.ws:
            return

        self.subscribed_tokens = token_list
        self.ws_url = "wss://starapi.prostocks.com/NorenWSTP/"

        def on_message(ws, message):
            print(f"\U0001f4e9 Raw WS Message: {message}")
            try:
                data = json.loads(message)
                if data.get("t") == "tk":
                    self.on_tick(data)
                    token = f"{data['e']}|{data['tk']}"
                    ltp = float(data['lp'])
                    vol = int(data.get('v', 0))
                    ts = datetime.strptime(data['ft'], "%d-%m-%Y %H:%M:%S")

                    for tf in self.TIMEFRAMES:
                        try:
                            minutes = int(tf.replace("min", ""))
                            bucket = ts.replace(second=0, microsecond=0, minute=(ts.minute // minutes) * minutes)
                            key = bucket.strftime("%Y-%m-%d %H:%M")

                            tf_data = self.candles.setdefault(token, {}).setdefault(tf, {})
                            c = tf_data.setdefault(key, {"O": ltp, "H": ltp, "L": ltp, "C": ltp, "V": vol})
                            c["C"] = ltp
                            c["H"] = max(c["H"], ltp)
                            c["L"] = min(c["L"], ltp)
                            c["V"] += vol
                        except Exception as e:
                            print(f"\ud83d\udd25 Error in candle build loop for TF {tf}: {e}")
            except Exception as e:
                print(f"\u274c Error in on_message: {e}")

        def on_open(ws):
            self.ws_connected = True
            print("\u2705 WebSocket connection opened.")
            for token in token_list:
                token_id = token.split("|")[1]
                payload = json.dumps({"t": "t", "k": [token_id]})
                ws.send(payload)
                print(f"\U0001f4e1 Subscribed to token: {payload}")

            def run_ping():
                while True:
                    try:
                        ws.send(json.dumps({"t": "ping"}))
                        time.sleep(15)
                    except:
                        break
            threading.Thread(target=run_ping, daemon=True).start()

        def on_close(ws, code, msg):
            print(f"\ud83d\udd0c WebSocket closed: {msg}")
            self.ws_connected = False
            self.ws = None
            time.sleep(2)
            print("\U0001f501 Reconnecting WebSocket...")
            self.start_candle_builder(self.subscribed_tokens)

        def on_error(ws, error):
            print(f"\u274c WebSocket Error: {error}")

        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_message=on_message,
            on_open=on_open,
            on_error=on_error,
            on_close=on_close
        )
        threading.Thread(target=self.ws.run_forever, daemon=True).start()

    def on_tick(self, data):
        print(f"\U0001f7e2 Tick received: {data}")
        token = data.get("tk")
        if not token:
            return

        if token not in {t.split("|")[1] for t in self.candle_tokens}:
            return

        try:
            ltp = float(data["lp"])
            ts = datetime.now().replace(second=0, microsecond=0)
            self.tick_data.setdefault(token, []).append((ts, ltp))
        except Exception as e:
            print(f"\ud83d\udd25 Error processing tick: {e}")

    def build_candles(self, token):
        if token not in self.tick_data:
            return []

        try:
            df = pd.DataFrame(self.tick_data[token], columns=["time", "price"])
            if df.empty:
                return []

            ohlc = df.groupby("time")["price"].agg(["first", "max", "min", "last"]).reset_index()
            ohlc.columns = ["time", "open", "high", "low", "close"]

            self.candle_data[token] = ohlc.to_dict("records")
            return self.candle_data[token]

        except Exception as e:
            print(f"\ud83d\udd25 Error building candles: {e}")
            return []

    def get_candles(self):
        return self.candle_data

    def get_all_candles(self):
        return self.candles

    def _post_json(self, url, payload):
        if not self.session_token:
            return {"stat": "Not_Ok", "emsg": "Not Logged In. Session Token Missing."}
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}&jKey={self.session_token}"
            print("\u2705 POST URL:", url)
            print("\U0001f4e6 Sent Payload:", jdata)
            response = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            print("\U0001f4e8 Response:", response.text)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    def get_watchlists(self):
        url = f"{self.base_url}/MWList"
        payload = {
            "uid": self.userid
        }
        return self._post_json(url, payload)

    def get_watchlist(self, wlname):
        url = f"{self.base_url}/MarketWatch"
        payload = {
            "uid": self.userid,
            "wlname": wlname
        }
        return self._post_json(url, payload)

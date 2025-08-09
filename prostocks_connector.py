
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

        # WebSocket vars
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
            print("📨 OTP Trigger Response:", response.text)
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
            print("🔁 Login Response Code:", response.status_code)
            print("📨 Login Response Body:", response.text)
            if response.status_code == 200:
                data = response.json()
                if data.get("stat") == "Ok":
                    self.session_token = data["susertoken"]
                    self.userid = data["uid"]
                    self.headers["Authorization"] = self.session_token
                    print("✅ Login Success!")
                    return True, self.session_token
                else:
                    return False, data.get("emsg", "Unknown login error")
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"RequestException: {e}"

    def add_token_for_candles(self, token):
        print(f"🪝 Adding token to candle builder: {token}")
        self.candle_tokens.add(token)

        if self.ws_connected and self.ws:
            try:
                token_id = token.split("|")[1]
                payload = json.dumps({"t": "t", "k": token_id})
                self.ws.send(payload)
                print(f"✅ WebSocket subscription sent: {payload}")
            except Exception as e:
                print(f"❌ Error sending subscription: {e}")
        else:
            print("⚠️ WebSocket not connected yet, token will subscribe on connect")

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
            try:
                data = json.loads(message)

                if "t" in data and data["t"] == "tk":
                    self.on_tick(data)
                elif "s" in data and data["s"] == "OK":
                    print(f"Subscription successful: {data}")
                else:
                    print(f"Unknown WS message: {data}")

            except Exception as e:
                print(f"Error in on_message: {e}")

        def on_open(ws):
            self.ws_connected = True
            print("🔗 WebSocket connection opened")
            for token in self.subscribed_tokens:
                token_id = token.split("|")[1]
                sub_msg = {"t": "t", "k": f"NSE|{token_id}"}
                ws.send(json.dumps(sub_msg))
                print(f"✅ Subscribed to token: NSE|{token_id}")

            def run_ping():
                while True:
                    try:
                        ws.send(json.dumps({"t": "ping"}))
                        time.sleep(15)
                    except:
                        break

            threading.Thread(target=run_ping, daemon=True).start()

        def on_close(ws, code, msg):
            print(f"🔌 WebSocket closed: {msg}")
            self.ws_connected = False
            self.ws = None
            time.sleep(2)
            print("🔁 Reconnecting WebSocket...")
            self.start_candle_builder(self.subscribed_tokens)

        def on_error(ws, error):
            print(f"❌ WebSocket Error: {error}")

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
        print(f"🟢 Tick received: {data}")
        token = data.get("tk")
        if not token:
            print("⚠️ No token in tick data")
            return

        if token not in self.candle_tokens:
            print(f"⚠️ Token {token} not in subscribed candle tokens: {self.candle_tokens}")
            return

        try:
            ltp = float(data["lp"])
            ts = datetime.now().replace(second=0, microsecond=0)
            self.tick_data.setdefault(token, []).append((ts, ltp))
            print(f"🧩 Appended Tick: {ts}, {ltp} for token {token}")
        except Exception as e:
            print(f"🔥 Error processing tick: {e}")

    def build_candles(self, token):
        print(f"🛠️ Building candles for token: {token}")
        if token not in self.tick_data:
            print("⚠️ No tick data found for token")
            return []

        try:
            df = pd.DataFrame(self.tick_data[token], columns=["time", "price"])
            if df.empty:
                print("⚠️ Tick DataFrame is empty")
                return []

            ohlc = df.groupby("time")["price"].agg(["first", "max", "min", "last"]).reset_index()
            ohlc.columns = ["time", "open", "high", "low", "close"]

            print(f"📊 Built {len(ohlc)} candles")
            self.candle_data[token] = ohlc.to_dict("records")
            return self.candle_data[token]

        except Exception as e:
            print(f"🔥 Error building candles: {e}")
            return []

    def get_candles(self):
        return self.candle_data

    def get_all_candles(self):
        return self.candles

    def get_watchlists(self):
        url = f"{self.base_url}/MWList"
        payload = {"uid": self.userid}
        return self._post_json(url, payload)

    def get_watchlist_names(self):
        resp = self.get_watchlists()
        if resp.get("stat") == "Ok":
            return sorted(resp["values"], key=int)
        return []

    def get_watchlist(self, wlname):
        url = f"{self.base_url}/MarketWatch"
        payload = {"uid": self.userid, "wlname": wlname}
        return self._post_json(url, payload)

    def search_scrip(self, search_text, exch="NSE"):
        url = f"{self.base_url}/SearchScrip"
        payload = {"uid": self.userid, "stext": search_text, "exch": exch}
        return self._post_json(url, payload)

    def add_scrips_to_watchlist(self, wlname, scrips_list):
        url = f"{self.base_url}/AddMultiScripsToMW"
        scrips_str = ",".join(scrips_list)
        payload = {"uid": self.userid, "wlname": wlname, "scrips": scrips_str}
        return self._post_json(url, payload)

    def delete_scrips_from_watchlist(self, wlname, scrips_list):
        url = f"{self.base_url}/DeleteMultiMWScrips"
        scrips_str = ",".join(scrips_list)
        payload = {"uid": self.userid, "wlname": wlname, "scrips": scrips_str}
        return self._post_json(url, payload)

    def _post_json(self, url, payload):
        if not self.session_token:
            return {"stat": "Not_Ok", "emsg": "Not Logged In. Session Token Missing."}
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}&jKey={self.session_token}"
            print("✅ POST URL:", url)
            print("📦 Sent Payload:", jdata)
            response = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            print("📨 Response:", response.text)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

def __init__(self, uid, password, base_url, ws_url):
        self.uid = uid
        self.password = password
        self.base_url = base_url
        self.ws_url = ws_url
        self.session = requests.Session()

        self.ws = None
        self.candles = []  # full candle history + forming candle
        self.current_candle = None
        self.tick_callback = None
        self.interval_minutes = 1

    # ------------------ HISTORICAL DATA ------------------

    def get_historical_data(self, exch, token, interval="1", days=1):
        """Fetch historical OHLC data from TPSeries endpoint."""
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days)

        payload = {
            "uid": self.uid,
            "exch": exch,
            "token": token,
            "st": start_dt.strftime("%Y-%m-%d %H:%M"),
            "et": end_dt.strftime("%Y-%m-%d %H:%M"),
            "intrv": interval
        }
        r = self.session.post(
            self.base_url + "/TPSeries",
            data={"jData": json.dumps(payload)}
        )
        r.raise_for_status()
        data = r.json()

        candles = []
        for c in data.get("values", []):
            candles.append({
                "time": datetime.strptime(c["time"], "%Y-%m-%d %H:%M"),
                "open": float(c["o"]),
                "high": float(c["h"]),
                "low": float(c["l"]),
                "close": float(c["c"]),
                "volume": int(c["v"])
            })
        self.candles = candles
        return candles

    # ------------------ LIVE WEBSOCKET ------------------
    def start_websocket(self, exch, token, interval=1, tick_callback=None):
        """Start WebSocket connection and stream live ticks."""
        self.interval_minutes = interval
        self.tick_callback = tick_callback

        def on_open(ws):
            # Authenticate
            ws.send(json.dumps({
                "t": "c",
                "uid": self.uid,
                "actid": self.uid,
                "pwd": self.password,
                "source": "API"
            }))
            time.sleep(1)
            # Subscribe to token
            ws.send(json.dumps({"t": "t", "k": f"{exch}|{token}"}))

        def on_message(ws, message):
            try:
                data = json.loads(message)
                if data.get("t") == "tk":
                    ltp = float(data["lp"])
                    volume = int(data.get("v", 0))
                    ts = datetime.now()
                    self._update_live_candle(ts, ltp, volume)

                    if self.tick_callback:
                        self.tick_callback(self.candles)  # full candle list for chart/strategy
            except Exception as e:
                print(f"Error in on_message: {e}")

        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=on_open,
            on_message=on_message
        )
        threading.Thread(target=self.ws.run_forever, daemon=True).start()

    # ------------------ CANDLE BUILDER ------------------
    def _update_live_candle(self, ts, price, volume):
        """Merge live tick into the current forming candle."""
        candle_start = ts.replace(second=0, microsecond=0)
        minute_block = (candle_start.minute // self.interval_minutes) * self.interval_minutes
        candle_start = candle_start.replace(minute=minute_block)

        # Start a new candle
        if not self.current_candle or self.current_candle["time"] != candle_start:
            if self.current_candle:
                # Push the completed candle to list
                self.candles.append(self.current_candle)
            self.current_candle = {
                "time": candle_start,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume
            }
        else:
            # Update existing candle
            self.current_candle["high"] = max(self.current_candle["high"], price)
            self.current_candle["low"] = min(self.current_candle["low"], price)
            self.current_candle["close"] = price
            self.current_candle["volume"] += volume

        # Always make sure last element is current candle
        if self.candles and self.candles[-1]["time"] == self.current_candle["time"]:
            self.candles[-1] = self.current_candle
        else:
            self.candles.append(self.current_candle)

        # Run strategy on updated candles
        self.run_strategy()



import requests
import hashlib
import json
import os
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta
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
        self.candles = {}          # Dict[token] = list of candles
        self.candle_tokens = set() # Set of tokens subscribed for candle building
        self.tick_data = {}        # Dict[token] = list of (datetime, price)
        self.candle_data = {}      # Dict[token] = cached candle dicts

        # For live candle builder (WebSocket + manual)
        self.current_candle = None
        self.live_candles = []  # For live candle list (1-min interval)
        self.interval_minutes = 1  # Candle interval for live update
        self.tick_callback = None  # Optional callback for live ticks

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
        token_id = token.split("|")[-1]  # Always get token ID only
        self.candle_tokens.add(token_id)  # Store token_id, not full token

        if self.ws_connected and self.ws:
            try:
                # Send full token with NSE| prefix when subscribing
                payload = json.dumps({"t": "t", "k": f"NSE|{token_id}"})
                self.ws.send(payload)
                print(f"✅ WebSocket subscription sent: {payload}")
            except Exception as e:
                print(f"❌ Error sending subscription: {e}")
        else:
            print("⚠️ WebSocket not connected yet, token will subscribe on connect")

        self.start_candle_builder(list(self.candle_tokens))
        self.start_candle_builder_loop()

    # ... rest of your methods ...


    def start_candle_builder_loop(self):
        def run():
            while True:
                for token in list(self.candle_tokens):
                    self.build_candles(token)
                time.sleep(10)

        threading.Thread(target=run, daemon=True).start()

    def start_candle_builder(self, token_list):
        if self.ws:
            return  # already started

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
                token_id = token.split("|")[-1]  # safer to always take last part
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
        token = data.get("tk")
        print(f"🟢 Tick received for token: {token}")

        # Normalize token: remove exchange prefix if present
        token_key = token.split("|")[-1] if token else None
        if not token_key:
            print("⚠️ Tick data missing token")
            return

        if token_key not in self.candle_tokens:
            print(f"⚠️ Token {token_key} not subscribed for candles")
            return

        try:
            ltp = float(data["lp"])
            ts = datetime.now().replace(second=0, microsecond=0)
            self.tick_data.setdefault(token_key, []).append((ts, ltp))
            print(f"🧩 Tick stored: {ts} {ltp} for token {token_key}")
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

        # ----------- Historical Data API -----------
    def get_historical_data(self, exch, token, interval="1", days=1):
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days)

        payload = {
            "uid": self.userid,
            "exch": exch,
            "token": token,
            "st": start_dt.strftime("%Y-%m-%d %H:%M"),
            "et": end_dt.strftime("%Y-%m-%d %H:%M"),
            "intrv": interval
        }
        try:
            r = self.session.post(
                self.base_url + "/TPSeries",
                data={"jData": json.dumps(payload)}
            )
            r.raise_for_status()
            print("🔍 Historical data raw response:", r.text)  # <-- Add this print
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
        except Exception as e:
            print(f"🔥 Error fetching historical data: {e}")
            return []

    # ----------- Live WebSocket + Candle Builder (alternative) -----------
    def start_websocket(self, exch, token, interval=1, tick_callback=None):
        """
        Start WebSocket connection and stream live ticks.
        tick_callback: function called with updated candle list after every tick.
        """
        self.interval_minutes = interval
        self.tick_callback = tick_callback

        def on_open(ws):
            # Authenticate (if needed) and subscribe
            # Your WS auth might be different; adjust accordingly
            ws.send(json.dumps({
                "t": "c",
                "uid": self.userid,
                "actid": self.userid,
                "pwd": self.password_plain,
                "source": "API"
            }))
            time.sleep(1)
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
                        self.tick_callback(self.live_candles)
            except Exception as e:
                print(f"Error in on_message: {e}")

        def on_error(ws, error):
            print(f"❌ WebSocket Error: {error}")

        def on_close(ws, close_status_code, close_msg):
            print(f"🔌 WebSocket closed: {close_status_code} - {close_msg}")

        self.ws = websocket.WebSocketApp(
            self.ws_url if hasattr(self, "ws_url") else "wss://starapi.prostocks.com/NorenWSTP/",
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        threading.Thread(target=self.ws.run_forever, daemon=True).start()

    def _update_live_candle(self, ts, price, volume):
        """
        Merge live tick into the current forming candle for the live_websocket method.
        """
        candle_start = ts.replace(second=0, microsecond=0)
        minute_block = (candle_start.minute // self.interval_minutes) * self.interval_minutes
        candle_start = candle_start.replace(minute=minute_block)

        if not self.current_candle or self.current_candle["time"] != candle_start:
            if self.current_candle:
                self.live_candles.append(self.current_candle)
            self.current_candle = {
                "time": candle_start,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume
            }
        else:
            self.current_candle["high"] = max(self.current_candle["high"], price)
            self.current_candle["low"] = min(self.current_candle["low"], price)
            self.current_candle["close"] = price
            self.current_candle["volume"] += volume

        # Update or append current candle in live_candles list
        if self.live_candles and self.live_candles[-1]["time"] == self.current_candle["time"]:
            self.live_candles[-1] = self.current_candle
        else:
            self.live_candles.append(self.current_candle)

    # ------------------ YOUR EXISTING ORDER, WATCHLIST, HOLDING APIs ------------------

    def place_order(self, order_params):
        """
        Place an order.
        order_params: dict with required order fields.
        """
        url = f"{self.base_url}/PlaceOrder"
        return self._post_json(url, order_params)

    def modify_order(self, order_params):
        url = f"{self.base_url}/ModifyOrder"
        return self._post_json(url, order_params)

    def cancel_order(self, order_params):
        url = f"{self.base_url}/CancelOrder"
        return self._post_json(url, order_params)

    def order_book(self):
        url = f"{self.base_url}/OrderBook"
        payload = {"uid": self.userid}
        return self._post_json(url, payload)

    def trade_book(self):
        url = f"{self.base_url}/TradeBook"
        payload = {"uid": self.userid}
        return self._post_json(url, payload)

    def holdings(self):
        url = f"{self.base_url}/Holding"
        payload = {"uid": self.userid}
        return self._post_json(url, payload)

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









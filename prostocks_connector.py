
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
    """ProStocks API wrapper with historical fetch + live websocket candle builder."""

    def __init__(self, userid=None, password_plain=None, vc=None, api_key=None, imei=None, base_url=None, apkversion="1.0.0"):
        self.userid = userid or os.getenv("PROSTOCKS_USER_ID")
        self.password_plain = password_plain or os.getenv("PROSTOCKS_PASSWORD")
        self.vc = vc or os.getenv("PROSTOCKS_VENDOR_CODE")
        self.api_key = api_key or os.getenv("PROSTOCKS_API_KEY")
        self.imei = imei or os.getenv("PROSTOCKS_MAC")
        self.base_url = (base_url or os.getenv("PROSTOCKS_BASE_URL") or "https://starapi.prostocks.com/NorenWClientTP").rstrip("/")
        self.apkversion = apkversion
        self.session_token = None
        self.session = requests.Session()
        self.headers = {"Content-Type": "text/plain"}

        # WebSocket / candle state
        self.ws = None
        self.ws_connected = False
        self.subscribed_tokens = []
        self.TIMEFRAMES = ["1min", "3min", "5min", "15min", "30min", "60min"]

        # candles: { token_id: { timeframe: { "YYYY-MM-DD HH:MM": {O,H,L,C,V} } } }
        self.candles = {}

        # tick_data: { token_id: [ (datetime, price, volume) ] }
        self.tick_data = {}

        # Token tracking for candle builder (FIX)
        self.candle_tokens = set()

        # live candle builder state
        self.current_candle = None
        self.interval_minutes = 1

    def sha256(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    # ---------------- Authentication / helper ----------------
    def send_otp(self):
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain or "")
        appkey_hash = self.sha256(f"{self.userid}|{self.api_key}")
        payload = {
            "uid": self.userid,
            "pwd": pwd_hash,
            "factor2": "",
            "vc": self.vc,
            "appkey": appkey_hash,
            "imei": self.imei,
            "apkversion": self.apkversion,
            "source": "API",
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
        pwd_hash = self.sha256(self.password_plain or "")
        appkey_hash = self.sha256(f"{self.userid}|{self.api_key}")
        payload = {
            "uid": self.userid,
            "pwd": pwd_hash,
            "factor2": factor2_otp,
            "vc": self.vc,
            "appkey": appkey_hash,
            "imei": self.imei,
            "apkversion": self.apkversion,
            "source": "API",
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

    # ---------------- Historical fetch ----------------
    def _intrv_from_tf(self, timeframe):
        mapping = {"1min": "1", "3min": "3", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
        return mapping.get(timeframe, "1")

    def fetch_historical_candles(self, token, timeframe="1min", days=1):
        try:
            parts = token.split("|")
            if len(parts) > 1:
                exch, token_id = parts
            else:
                exch, token_id = "NSE", parts[0]

            intrv = self._intrv_from_tf(timeframe)
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=days)

            payload = {
                "uid": self.userid,
                "exch": exch,
                "token": token_id,
                "st": start_dt.strftime("%Y-%m-%d %H:%M"),
                "et": end_dt.strftime("%Y-%m-%d %H:%M"),
                "intrv": intrv,
            }

            url = self.base_url + "/TPSeries"
            r = self.session.post(url, data={"jData": json.dumps(payload)}, timeout=10)
            print(f"🔍 Historical data raw response for {exch}|{token_id} ({timeframe}):", r.text)
            r.raise_for_status()
            data = r.json()
            values = data.get("values") or []

            self.candles.setdefault(token_id, {})
            tf_store = {}
            for c in values:
                tstr = c.get("time")
                try:
                    dt = datetime.strptime(tstr, "%Y-%m-%d %H:%M")
                    tf_store[dt.strftime("%Y-%m-%d %H:%M")] = {
                        "O": float(c.get("o", 0)),
                        "H": float(c.get("h", 0)),
                        "L": float(c.get("l", 0)),
                        "C": float(c.get("c", 0)),
                        "V": int(c.get("v", 0))
                    }
                except Exception as ex:
                    print(f"⚠️ Skipping invalid historical row: {c} -> {ex}")

            self.candles[token_id][timeframe] = tf_store
            print(f"📈 Loaded {len(tf_store)} historical candles for {exch}|{token_id} @ {timeframe}")
            return tf_store

        except Exception as e:
            print(f"❌ Historical fetch failed for {token} {timeframe}: {e}")
            return {}

    # ---------------- Candle subscription & websocket ----------------
    def add_token_for_candles(self, token_full):
        if "|" in token_full:
            exch, token_id = token_full.split("|", 1)
        else:
            exch, token_id = "NSE", token_full

        print(f"🪝 Adding token to candle builder: {exch}|{token_id}")
        self.candles.setdefault(token_id, {})

        for tf in ["1min", "5min", "15min"]:
            self.fetch_historical_candles(f"{exch}|{token_id}", timeframe=tf, days=1)

        self.candle_tokens.add(token_id)

        if self.ws_connected and self.ws:
            try:
                payload = json.dumps({"t": "t", "k": f"{exch}|{token_id}"})
                self.ws.send(payload)
                print(f"✅ WebSocket subscription sent: {payload}")
            except Exception as e:
                print(f"❌ Error sending subscription: {e}")
        else:
            print("⚠️ WebSocket not connected yet, token will subscribe on connect")

        self.start_candle_builder(list({f"{exch}|{tid}" for tid in self.candle_tokens}))
        self.start_candle_builder_loop()

    def start_candle_builder_loop(self):
        def run():
            while True:
                for token_id in list(self.candle_tokens):
                    try:
                        self._aggregate_tick_data_to_tf(token_id, "1min")
                    except Exception as ex:
                        print("🔥 Error in candle builder loop:", ex)
                time.sleep(2)

        if not getattr(self, "_candle_loop_started", False):
            threading.Thread(target=run, daemon=True).start()
            self._candle_loop_started = True

    def start_candle_builder(self, token_list):
        self.subscribed_tokens = token_list
        self.ws_url = "wss://starapi.prostocks.com/NorenWSTP/"

        def on_message(ws, message):
            try:
                data = json.loads(message)
                if data.get("t") == "tk":
                    self.on_tick(data)
                elif data.get("s") == "OK":
                    print(f"Subscription successful: {data}")
            except Exception as e:
                print(f"Error in on_message: {e}")

        def on_open(ws):
            self.ws_connected = True
            print("🔗 WebSocket connection opened")
            for token in self.subscribed_tokens:
                try:
                    parts = token.split("|")
                    if len(parts) > 1:
                        exch, token_id = parts
                    else:
                        exch, token_id = "NSE", parts[0]
                    sub_msg = {"t": "t", "k": f"{exch}|{token_id}"}
                    ws.send(json.dumps(sub_msg))
                    print(f"✅ Subscribed to token: {exch}|{token_id}")
                except Exception as e:
                    print("❌ Sub error:", e)

            def run_ping():
                while True:
                    try:
                        ws.send(json.dumps({"t": "ping"}))
                        time.sleep(15)
                    except Exception:
                        break

            threading.Thread(target=run_ping, daemon=True).start()

        def on_close(ws, code, msg):
            print(f"🔌 WebSocket closed: {msg}")
            self.ws_connected = False
            self.ws = None
            time.sleep(2)
            print("🔁 Reconnecting WebSocket...")
            try:
                self.start_candle_builder(self.subscribed_tokens)
            except Exception as e:
                print("Reconnect failed:", e)

        def on_error(ws, error):
            print(f"❌ WebSocket Error: {error}")

        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_message=on_message,
            on_open=on_open,
            on_error=on_error,
            on_close=on_close,
        )
        threading.Thread(target=self.ws.run_forever, daemon=True).start()

    # ---------------- Tick handling & aggregation ----------------
    def on_tick(self, data):
        token = data.get("tk")
        print(f"🟢 Tick received for token: {token}")
        if not token:
            return

        token_id = token.split("|")[-1]
        try:
            ltp = float(data.get("lp", 0))
        except Exception:
            ltp = 0.0
        try:
            vol = int(float(data.get("v", 0)))
        except Exception:
            vol = 0

        ts = datetime.now().replace(second=0, microsecond=0)
        self.tick_data.setdefault(token_id, []).append((ts, ltp, vol))
        print(f"🧩 Tick stored: {ts} {ltp} vol={vol} for token {token_id}")

        try:
            self._aggregate_tick_data_to_tf(token_id, "1min")
        except Exception as e:
            print("🔥 Error aggregating tick to candle:", e)

    def _aggregate_tick_data_to_tf(self, token_id, timeframe="1min"):
        ticks = self.tick_data.get(token_id, [])
        if not ticks:
            return

        by_min = {}
        for ts, price, vol in ticks:
            key = ts.strftime("%Y-%m-%d %H:%M")
            by_min.setdefault(key, []).append((price, vol))

        self.candles.setdefault(token_id, {})
        tf_store = self.candles[token_id].get(timeframe, {})

        for key, arr in by_min.items():
            prices = [p for p, v in arr if p is not None]
            vols = [v for p, v in arr]
            if not prices:
                continue
            O = prices[0]
            H = max(prices)
            L = min(prices)
            C = prices[-1]
            V = sum(vols)
            tf_store[key] = {"O": O, "H": H, "L": L, "C": C, "V": V}

        self.candles[token_id][timeframe] = tf_store

    # ---------------- convenience getters ----------------
    def get_candles(self):
        return self.candles

    def get_all_candles(self):
        return self.candles

    # ---------------- existing order/watchlist helpers ----------------
    def place_order(self, order_params):
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

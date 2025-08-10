
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
    """ProStocks API wrapper with historical fetch + live websocket candle builder.

    Key improvements in this merged version:
    - fetch_historical_candles(): fetches TPSeries historical OHLC and stores in
      self.candles[token_id][timeframe] as a dict keyed by "YYYY-MM-DD HH:MM"
      with values {"O","H","L","C","V"} which matches dashboard expectations.
    - add_token_for_candles(): fetches historical candles (for available TIMEFRAMES)
      before subscribing to WebSocket so charts show past + live data.
    - Robust websocket subscription (sends "NSE|<token>" form) and on_message/on_tick
      stores tick as (ts, price, volume) and updates candle store for "1min".
    """

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
        self.subscribed_tokens = []               # list of strings like "NSE|11872"
        self.TIMEFRAMES = ["1min", "3min", "5min", "15min", "30min", "60min"]

        # candles: { token_id: { timeframe: { "YYYY-MM-DD HH:MM": {O,H,L,C,V} } } }
        self.candles = {}

        # tick_data: { token_id: [ (datetime, price, volume) ] }
        self.tick_data = {}

        # live candle builder state (optional)
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
        # map dashboard timeframe to TPSeries intrv value
        mapping = {"1min": "1", "3min": "3", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
        return mapping.get(timeframe, "1")

    def fetch_historical_candles(self, token, timeframe="1min", days=1):
        """Fetch historical OHLC from TPSeries and store into self.candles[token_id][timeframe].

        token can be "NSE|11872" or "11872".
        """
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

            # ensure structure
            self.candles.setdefault(token_id, {})
            tf_store = {}
            for c in values:
                # expected keys: time, o, h, l, c, v
                tstr = c.get("time")
                try:
                    # Normalise time string to 'YYYY-MM-DD HH:MM'
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
        """Add token (NSE|id or id) for both historical fetch and live subscription."""
        if "|" in token_full:
            exch, token_id = token_full.split("|", 1)
        else:
            exch, token_id = "NSE", token_full

        print(f"🪝 Adding token to candle builder: {exch}|{token_id}")
        # ensure candle containers exist
        self.candles.setdefault(token_id, {})

        # fetch historical for a few useful timeframes (so switching TF in dashboard is faster)
        for tf in ["1min", "5min", "15min"]:
            # do not block websocket thread for long — keep small days window for intraday
            self.fetch_historical_candles(f"{exch}|{token_id}", timeframe=tf, days=1)

        # store token id in set
        self.candle_tokens.add(token_id)

        # send ws subscription if connected
        if self.ws_connected and self.ws:
            try:
                payload = json.dumps({"t": "t", "k": f"{exch}|{token_id}"})
                self.ws.send(payload)
                print(f"✅ WebSocket subscription sent: {payload}")
            except Exception as e:
                print(f"❌ Error sending subscription: {e}")
        else:
            print("⚠️ WebSocket not connected yet, token will subscribe on connect")

        # ensure builder loop running
        self.start_candle_builder(list({f"{exch}|{tid}" for tid in self.candle_tokens}))
        self.start_candle_builder_loop()

    def start_candle_builder_loop(self):
        def run():
            while True:
                for token_id in list(self.candle_tokens):
                    # update 1min aggregated candles from tick buffer
                    try:
                        self._aggregate_tick_data_to_tf(token_id, "1min")
                    except Exception as ex:
                        print("🔥 Error in candle builder loop:", ex)
                time.sleep(2)

        # only one background thread
        if not getattr(self, "_candle_loop_started", False):
            threading.Thread(target=run, daemon=True).start()
            self._candle_loop_started = True

    def start_candle_builder(self, token_list):
        """Start websocket and subscribe to token_list (items like 'NSE|11872')."""
        # update subscribed list
        self.subscribed_tokens = token_list
        self.ws_url = "wss://starapi.prostocks.com/NorenWSTP/"

        def on_message(ws, message):
            try:
                data = json.loads(message)
                # debug: print incoming tick messages (can be noisy)
                # print("WS MSG:", data)
                if data.get("t") == "tk":
                    self.on_tick(data)
                elif data.get("s") == "OK":
                    print(f"Subscription successful: {data}")
                else:
                    # other control messages
                    pass
            except Exception as e:
                print(f"Error in on_message: {e}")

        def on_open(ws):
            self.ws_connected = True
            print("🔗 WebSocket connection opened")
            # subscribe to each token (server expects exch|token form)
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
            # attempt reconnect
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
        """Handle incoming tick message from WS. Expected keys: 'tk' (token), 'lp' (last price), 'v' maybe volume."""
        token = data.get("tk")  # often like "NSE|18124"
        print(f"🟢 Tick received for token: {token}")
        if not token:
            return

        token_id = token.split("|")[-1]
        # ensure we store volume if available
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

        # update aggregated 1min candle immediately (fast feedback for dashboard)
        try:
            self._aggregate_tick_data_to_tf(token_id, "1min")
        except Exception as e:
            print("🔥 Error aggregating tick to candle:", e)

    def _aggregate_tick_data_to_tf(self, token_id, timeframe="1min"):
        """Aggregate tick_data[token_id] into timeframe and store in self.candles[token_id][timeframe].
        Only aggregates the minutes present in tick buffer; keeps historical data too.
        """
        ticks = self.tick_data.get(token_id, [])
        if not ticks:
            return

        # create map minute -> list of (price, vol)
        by_min = {}
        for ts, price, vol in ticks:
            key = ts.strftime("%Y-%m-%d %H:%M")
            by_min.setdefault(key, []).append((price, vol))

        # ensure structure
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

        # save back
        self.candles[token_id][timeframe] = tf_store

    # ---------------- convenience getters ----------------
    def get_candles(self):
        return self.candles

    def get_all_candles(self):
        return self.candles

    # ---------------- API helpers (existing) ----------------
    def start_websocket(self, exch, token, interval=1, tick_callback=None):
        """Legacy helper that starts a websocket and builds live candles into self.live_candles.
        Prefer using start_candle_builder() / add_token_for_candles() for the merged flow.
        """
        self.interval_minutes = interval
        self.tick_callback = tick_callback

        def on_open(ws):
            ws.send(json.dumps({"t": "c", "uid": self.userid, "actid": self.userid, "pwd": self.password_plain, "source": "API"}))
            time.sleep(1)
            ws.send(json.dumps({"t": "t", "k": f"{exch}|{token}"}))

        def on_message(ws, message):
            try:
                data = json.loads(message)
                if data.get("t") == "tk":
                    ltp = float(data.get("lp", 0))
                    volume = int(data.get("v", 0))
                    ts = datetime.now()
                    # legacy behavior: update a live candle list
                    self._update_live_candle(ts, ltp, volume)
                    if self.tick_callback:
                        self.tick_callback(self.live_candles)
            except Exception as e:
                print(f"Error in on_message (legacy): {e}")

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
        """Legacy in-memory 1-min candle builder for live_websocket path."""
        candle_start = ts.replace(second=0, microsecond=0)
        minute_block = (candle_start.minute // self.interval_minutes) * self.interval_minutes
        candle_start = candle_start.replace(minute=minute_block)

        if not self.current_candle or self.current_candle["time"] != candle_start:
            if self.current_candle:
                self.live_candles.append(self.current_candle)
            self.current_candle = {"time": candle_start, "open": price, "high": price, "low": price, "close": price, "volume": volume}
        else:
            self.current_candle["high"] = max(self.current_candle["high"], price)
            self.current_candle["low"] = min(self.current_candle["low"], price)
            self.current_candle["close"] = price
            self.current_candle["volume"] += volume

        if self.live_candles and self.live_candles[-1]["time"] == self.current_candle["time"]:
            self.live_candles[-1] = self.current_candle
        else:
            self.live_candles.append(self.current_candle)

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

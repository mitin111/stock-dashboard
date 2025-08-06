
import requests
import hashlib
import json
import os
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta
import websocket
import threading

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

        # WebSocket Candle Builder
        self.ws = None
        self.tokens = []  # e.g., ["NSE|11872"]
        self.TIMEFRAMES = [1, 3, 5, 15, 30, 60]
        self.candles = {}  # Format: candles[token][tf_key][timestamp] = {O, H, L, C, V}

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

    # === WebSocket Helpers ===

    def floor_time(self, dt, minutes):
        return dt - timedelta(minutes=dt.minute % minutes, seconds=dt.second, microseconds=dt.microsecond)

    def start_candle_builder(self, tokens):
        self.tokens = tokens
        self.candles = {}  # Reset candles

    def get_candles(self):
        return self.candles

        def get_watchlist_tokens(self):
            # Return list of all tokens from all watchlists
            return list(self.candles.keys())

        def on_message(ws, message):
            data = json.loads(message)

            if data.get("tk") and data.get("lp"):  # Tick with price
                token = data["tk"]
                ltp = float(data["lp"])
                vol = int(data.get("v", 0))
                now = datetime.now()

                if token not in self.candles:
                    self.candles[token] = {}

                for tf in self.TIMEFRAMES:
                    tf_key = f"{tf}min"
                    tf_time = self.floor_time(now, tf).strftime("%Y-%m-%d %H:%M")

                    if tf_key not in self.candles[token]:
                        self.candles[token][tf_key] = {}

                    if tf_time not in self.candles[token][tf_key]:
                        self.candles[token][tf_key][tf_time] = {
                            "O": ltp, "H": ltp, "L": ltp, "C": ltp, "V": vol
                        }
                    else:
                        c = self.candles[token][tf_key][tf_time]
                        c["H"] = max(c["H"], ltp)
                        c["L"] = min(c["L"], ltp)
                        c["C"] = ltp
                        c["V"] += vol

                    if tf == 1:
                        print(f"[{tf_key}] 🕒 {tf_time} | {token} | O:{c['O']} H:{c['H']} L:{c['L']} C:{c['C']} V:{c['V']}")

        def on_open(ws):
            print("✅ WebSocket opened")
            ws.send(json.dumps({
                "uid": self.userid,
                "actid": self.userid,
                "source": "API",
                "susertoken": self.session_token
            }))
            time.sleep(1)
            for t in self.tokens:
                ws.send(json.dumps({"t": "t", "k": t}))
                print(f"📡 Subscribed to tick: {t}")

        def on_error(ws, error):
            print("❌ WebSocket Error:", error)

        def on_close(ws, code, msg):
            print("🔌 WebSocket closed:", msg)

        self.ws = websocket.WebSocketApp(
            "wss://starapi.prostocks.com/NorenWSTP/",
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )

        threading.Thread(target=self.ws.run_forever, daemon=True).start()

    # === Watchlist & Helpers ===

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




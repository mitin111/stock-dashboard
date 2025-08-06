
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
        self.subscribed_tokens = []
        self.TIMEFRAMES = ["1min", "3min", "5min", "15min", "30min", "60min"]
        self.candles = {}

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

    def start_candle_builder(self, token_list):
        if self.ws:
            return

        self.subscribed_tokens = token_list
        self.candles = {}
        self.ws_url = "wss://starapi.prostocks.com/NorenWSTP/"

        def on_message(ws, message):
            try:
                data = json.loads(message)
                if data.get("t") != "tk":
                    return

                token = f"{data['e']}|{data['tk']}"
                ltp = float(data['lp'])
                vol = int(data.get('v', 0))
                ts = datetime.strptime(data['ft'], "%d-%m-%Y %H:%M:%S")
                print(f"📥 Live tick from token: {token}")

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

                       # ✅ ADD THESE DEBUG PRINTS:
                       print(f"🕒 Timeframe: {tf}")
                       print(f"🧩 Candle Key: {key}")
                       print(f"📊 Updated Candle: {self.candles[token][tf][key]}")
    
               except Exception as e:
                   print(f"🔥 Error in candle build loop for TF {tf}: {e}")

        def on_open(ws):
            print("✅ WebSocket connection opened.")
            for token in token_list:
                ws.send(json.dumps({"t": "t", "k": token}))
                print(f"📡 Subscribed to tick: {token}")

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
            self.ws = None
            time.sleep(2)
            print("🔄 Reconnecting WebSocket...")
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

    def get_candles(self):
        return self.candles

    def get_watchlist_tokens(self):
        return list(self.candles.keys())

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







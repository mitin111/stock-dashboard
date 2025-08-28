# prostocks_connector.py
import requests
import hashlib
import json
import os
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import pandas as pd
import websocket
import threading

load_dotenv()


class ProStocksAPI:
    def __init__(
        self,
        userid=None,
        password_plain=None,
        vc=None,
        api_key=None,
        imei=None,
        base_url=None,
        apkversion="1.0.0"
    ):
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

        # --- WebSocket state ---
        self.ws = None
        self.is_ws_connected = False
        self._sub_tokens = []
        self.tick_file = "ticks.log"
        self.ws_url = "wss://starapi.prostocks.com/NorenWSTP/"

        # ✅ Tick Queue + File init YAHAN karna hai
        import queue
        self.tick_queue = queue.Queue()
        self.tick_file = "ticks.log"

    # ---------------- Utils ----------------
    def sha256(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    # ---------------- Auth ----------------
    def send_otp(self):
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_raw = f"{self.userid}|{self.api_key}"
        appkey_hash = self.sha256(appkey_raw)

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
        appkey_raw = f"{self.userid}|{self.api_key}"
        appkey_hash = self.sha256(appkey_raw)

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

    # ------------- Core POST helper -------------
    def _post_json(self, url, payload):
        if not self.session_token:
            return {"stat": "Not_Ok", "emsg": "Not Logged In. Session Token Missing."}
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}&jKey={self.session_token}"
            print("✅ POST URL:", url)
            print("📦 Sent Payload:", jdata)

            response = self.session.post(
                url,
                data=raw_data,
                headers={"Content-Type": "text/plain"},
                timeout=15
            )
            print("📨 Response:", response.text)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    # ------------- Watchlists -------------
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

       # ------------- TPSeries -------------
    def get_tpseries(self, exch, token, interval="5", st=None, et=None):
        """
        Returns raw TPSeries from API.
        For success, the API typically returns a list; on error it returns a dict with 'stat'/'emsg'.
        'st' and 'et' must be epoch seconds (UTC).
        """
        if not self.session_token:
            return {"stat": "Not_Ok", "emsg": "Session token missing. Please login again."}

        # Default window (last 60 days) if not provided
        if st is None or et is None:
            days_back = 60
            et_dt = datetime.now(timezone.utc)
            st_dt = et_dt - timedelta(days=days_back)
            st = int(st_dt.timestamp())
            et = int(et_dt.timestamp())

        url = f"{self.base_url}/TPSeries"
        payload = {
            "uid": self.userid,
            "exch": exch,
            "token": str(token),
            "st": str(st),
            "et": str(et),
            "intrv": str(interval)
        }

        print("📤 Sending TPSeries Payload:")
        print(f"  UID    : {payload['uid']}")
        print(f"  EXCH   : {payload['exch']}")
        print(f"  TOKEN  : {payload['token']}")
        print(f"  ST     : {payload['st']} → {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int(st)))} UTC")
        print(f"  ET     : {payload['et']} → {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int(et)))} UTC")
        print(f"  INTRV  : {payload['intrv']}")

        try:
            response = self._post_json(url, payload)
            return response
        except Exception as e:
            print("❌ Exception in get_tpseries():", e)
            return {"stat": "Not_Ok", "emsg": str(e)}

    # ---------------- TPSeries fetch ----------------
    def fetch_full_tpseries(self, exch, token, interval="5", chunk_days=5, max_days=60):
        all_chunks = []
        end_dt = datetime.now(timezone.utc)
        start_limit_dt = end_dt - timedelta(days=max_days)

        while end_dt > start_limit_dt:
            start_dt = end_dt - timedelta(days=chunk_days)
            if start_dt < start_limit_dt:
                start_dt = start_limit_dt

            st = int(start_dt.timestamp())
            et = int(end_dt.timestamp())
            print(f"⏳ Fetching {start_dt} → {end_dt} (UTC)")
            resp = self.get_tpseries(exch, token, interval, st, et)

            if isinstance(resp, dict):
                print(f"⚠️ TPSeries chunk returned dict: {resp.get('emsg') or resp.get('stat')}")
                end_dt = start_dt - timedelta(seconds=1)
                time.sleep(0.25)
                continue

            if not isinstance(resp, list) or len(resp) == 0:
                print("⚠️ Empty chunk. Moving back…")
                end_dt = start_dt - timedelta(seconds=1)
                time.sleep(0.25)
                continue

            df_chunk = pd.DataFrame(resp)
            all_chunks.append(df_chunk)
            end_dt = start_dt - timedelta(seconds=1)
            time.sleep(0.25)

        if not all_chunks:
            return pd.DataFrame()

        df = pd.concat(all_chunks, ignore_index=True)

        if "time" in df.columns:
            df.drop_duplicates(subset=["time"], inplace=True)
            df.sort_values(by="time", inplace=True)

        rename_map = {
            "time": "datetime",
            "into": "open",
            "inth": "high",
            "intl": "low",
            "intc": "close",
            "intvwap": "vwap",
            "intv": "volume",
            "intol": "open_interest_lot",
            "oi": "open_interest"
        }
        df.rename(columns=rename_map, inplace=True)

        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce", dayfirst=True)
            df = df.dropna(subset=["datetime"])

        df.sort_values("datetime", inplace=True)
        return df.reset_index(drop=True)

    def fetch_tpseries_for_watchlist(self, wlname, interval="5"):
        results = []
        MAX_CALLS_PER_MIN = 20
        call_count = 0

        symbols = self.get_watchlist(wlname)
        if not symbols or "values" not in symbols:
            print("❌ No symbols found in watchlist.")
            return []

        for idx, sym in enumerate(symbols["values"]):
            exch = sym.get("exch", "").strip()
            token = str(sym.get("token", "")).strip()
            symbol = sym.get("tsym", "").strip()

            if not token.isdigit():
                print(f"⚠️ Skipping {symbol}: Invalid token")
                continue

            try:
                print(f"\n📦 {idx+1}. {symbol} → {exch}|{token}")
                df = self.fetch_full_tpseries(exch, token, interval)
                if not df.empty:
                    print(f"✅ {symbol}: {len(df)} candles fetched.")
                    results.append({"symbol": symbol, "data": df})
                else:
                    print(f"⚠️ {symbol}: No data fetched.")
            except Exception as e:
                print(f"❌ {symbol}: Exception: {e}")

            call_count += 1
            if call_count >= MAX_CALLS_PER_MIN:
                print("⚠️ TPSeries limit reached. Skipping remaining.")
                break

        return results

  # ---------------- WebSocket helpers ----------------
    def _ws_on_message(self, ws, message):
        try:
            tick = json.loads(message)
            # Optional: login-ack handle (ProStocks me 'ck' aata hai)
            if isinstance(tick, dict) and tick.get("t") == "ck":
                if tick.get("s") in ["OK", "Ok"]:   # <-- FIXED ✅
                    print("✅ WebSocket login OK")
                    # re-subscribe after login ack if tokens present
                    if hasattr(self, "_sub_tokens") and self._sub_tokens:
                        self.subscribe_tokens(self._sub_tokens)
                else:
                    print("❌ WebSocket login failed:", tick)
                return

            # 📩 Normal tick data
            print("📩 Tick received:", tick)

            # ✅ File me append karo
            with open(self.tick_file, "a") as f:
                f.write(json.dumps(tick) + "\n")
                
            # ✅ Queue me bhejo (safe for Streamlit consumer thread)
            self.tick_queue.put(tick)
                
            # Callback trigger
            if hasattr(self, "_on_tick") and self._on_tick:
                try:
                    self._on_tick(tick)
                except Exception as e:
                    print("❌ on_tick callback error:", e)

            # ✅ Live candle builder update
            try:
                self.build_live_candles_from_tick(tick)
            except Exception as e:
                print("⚠️ candle build error:", e)
                
        except Exception as e:
            print("⚠️ _ws_on_message parse error:", e)

    def _ws_on_open(self, ws):
        self.is_ws_connected = True
        print("✅ WebSocket connected")

        # Login packet (UID/JKEY dynamically from successful REST login)
        login_pkt = {
            "t": "c",
            "uid": self.userid,
            "actid": self.userid,
            "susertoken": self.session_token,
            "source": "API",
        }
        ws.send(json.dumps(login_pkt))
        print("🔑 WS login sent")

    def _ws_on_close(self, ws, code, msg):
        self.is_ws_connected = False
        print("❌ WebSocket closed:", code, msg)

    def _ws_on_error(self, ws, error):
        print("⚠️ WebSocket error:", error)

    def subscribe_tokens(self, tokens):
        """
        tokens: list[str] in 'EXCH|TOKEN' format.
        ProStocks WS supports multi-subscribe with '#' separator.
        """
        if not self.ws:
            print("⚠️ subscribe_tokens: WS not connected yet")
            return
        if not tokens:
            print("⚠️ subscribe_tokens: Empty token list")
            return

        # unique + keep order
        uniq = []
        seen = set()
        for k in tokens:
            if k and k not in seen:
                uniq.append(k)
                seen.add(k)

        sub_req = {"t": "t", "k": "#".join(uniq)}
        try:
            self.ws.send(json.dumps(sub_req))
            print(f"📡 Subscribed: {uniq}")
        except Exception as e:
            print("❌ subscribe_tokens error:", e)

    def start_ticks(self, symbols, tick_file="ticks.log"):
        """
        Start WebSocket and record every incoming tick to `tick_file`.
        `symbols` can be:
          - ['NSE|26000','NSE|500209'] style strings, OR
          - [{'exch':'NSE','token':'26000'}, ...] dicts.
        Pre-requisite: call login() successfully to populate self.session_token.
        """
        if not self.session_token or not self.userid:
            raise RuntimeError("Not logged in: call login() first and ensure session_token is set.")

        # normalize symbols
        if not symbols or not isinstance(symbols, (list, tuple)):
            raise ValueError("symbols must be a non-empty list/tuple")

        if isinstance(symbols[0], dict):
            tokens = []
            for s in symbols:
                exch = str(s.get("exch", "")).strip()
                tok  = str(s.get("token", "")).strip()
                if exch and tok:
                    tokens.append(f"{exch}|{tok}")
        else:
            tokens = [str(s).strip() for s in symbols if s and isinstance(s, str)]

        if not tokens:
            raise ValueError("No valid symbols to subscribe")

        self._sub_tokens = tokens
        self.tick_file = tick_file

        # Build WS URL (only u & t required)
        url = f"{self.ws_url}?u={self.userid}&t={self.session_token}"
        print("🔗 Connecting WS:", url)

        self.ws = websocket.WebSocketApp(
            url,
            on_open=self._ws_on_open,
            on_message=self._ws_on_message,
            on_error=self._ws_on_error,
            on_close=self._ws_on_close,
        )

        # optional heartbeat thread
        def _send_heartbeat(wsobj):
            while True:
                if self.is_ws_connected:
                    try:
                        wsobj.send(json.dumps({"t": "h"}))  # heartbeat
                        # print("💓 ping sent")
                    except Exception as e:
                        print("⚠️ heartbeat error:", e)
                time.sleep(30)

        threading.Thread(target=_send_heartbeat, args=(self.ws,), daemon=True).start()

        # run forever in background
        self._ws_thread = threading.Thread(
            target=self.ws.run_forever,
            kwargs={"ping_interval": 30, "ping_timeout": 10},
            daemon=True,
        )
        self._ws_thread.start()
        print("▶️ WS thread started")

    def stop_ticks(self):
        try:
            if self.ws:
                self.ws.close()
                print("🛑 WebSocket stop requested")
        except Exception as e:
            print("❌ stop_ticks error:", e)

    def connect_websocket(self, symbols, on_tick=None, tick_file="ticks.log"):
        """
        Wrapper so that dashboard call works.
        Internally uses start_ticks.
        """
        self._on_tick = on_tick
        self.start_ticks(symbols, tick_file=tick_file)

        # Wait until WS connected (max 5 sec)
        for _ in range(50):
            if self.is_ws_connected:
                return True
            time.sleep(0.1)
        return False    
        












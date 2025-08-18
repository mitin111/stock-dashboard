
# prostocks_connector.py
import requests
import hashlib
import json
import os
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import pandas as pd

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

                # ------------- TPSeries + WebSocket Live Candles -------------

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

    def fetch_full_tpseries(self, exch, token, interval="5", chunk_days=5, max_days=60):
        """
        Chunked fetch of TPSeries over 'max_days' lookback combining results into a clean DataFrame
        ready for candlestick charting (open, high, low, close, volume, datetime).
        """
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

            # Error from API
            if isinstance(resp, dict):
                print(f"⚠️ TPSeries chunk returned dict: {resp.get('emsg') or resp.get('stat')}")
                end_dt = start_dt - timedelta(seconds=1)
                time.sleep(0.25)
                continue

            # Empty chunk
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

        # Combine
        df = pd.concat(all_chunks, ignore_index=True)

        # Deduplicate & sort by original 'time' if present
        if "time" in df.columns:
            df.drop_duplicates(subset=["time"], inplace=True)
            df.sort_values(by="time", inplace=True)

        # ✅ Correct rename mapping
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

        # Safe datetime parsing
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(
                df["datetime"],
                errors="coerce",
                dayfirst=True
            )
            df = df.dropna(subset=["datetime"])

        # Final sort & reset
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

    def start_websocket_for_symbol(self, symbol):
    import websocket, json, threading
    from datetime import datetime

    def on_message(ws, message):
        print("📩 Tick message raw:", message)   # 👈 Debug log
        try:
            tick = json.loads(message)
        except Exception as e:
            print("❌ JSON decode error:", e)
            return

        if tick.get("t") != "tk":   # sirf tick messages process karo
            print("⚠️ Non-tick message:", tick)
            return

        ts = datetime.fromtimestamp(int(tick["ft"]) / 1000)
        minute = ts.replace(second=0, microsecond=0)
        price = float(tick["lp"])
        vol = int(tick.get("v", 1))

        df = st.session_state.get("candles_df", pd.DataFrame())

        if not df.empty and df.iloc[-1]["Datetime"] == minute:
            # Update current candle
            df.at[df.index[-1], "High"] = max(df.iloc[-1]["High"], price)
            df.at[df.index[-1], "Low"] = min(df.iloc[-1]["Low"], price)
            df.at[df.index[-1], "Close"] = price
            df.at[df.index[-1], "Volume"] += vol
        else:
            # New candle
            new_candle = pd.DataFrame(
                [[minute, price, price, price, price, vol]],
                columns=["Datetime", "Open", "High", "Low", "Close", "Volume"]
            )
            df = pd.concat([df, new_candle], ignore_index=True)

        st.session_state["candles_df"] = df
        print("✅ Candle updated:", df.tail(1).to_dict("records"))

    def on_open(ws):
        print("✅ WebSocket connected!")  # 👈 Debug log
        sub = json.dumps({"t": "t", "k": symbol})
        ws.send(sub)
        print(f"📡 Subscribed to {symbol}")  # 👈 Debug log

    def on_error(ws, error):
        print("❌ WebSocket error:", error)

    def on_close(ws, code, msg):
        print("🔌 WebSocket closed:", code, msg)

    self.ws = websocket.WebSocketApp(
        "wss://starapi.prostocks.com/NorenWSTP/",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    threading.Thread(target=self.ws.run_forever, daemon=True).start()

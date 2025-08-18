
# prostocks_connector.py
import requests
import hashlib
import json
import os
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import pandas as pd
import streamlit as st  # websocket candles ke liye

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

    def normalize_tpseries_data(self, raw_data):
        """
        Convert TPSeries raw response (list of lists) to OHLCV DataFrame
        Format: [epoch, open, high, low, close, volume]
        """
        if not raw_data or not isinstance(raw_data, list):
            return pd.DataFrame()

        try:
            df = pd.DataFrame(raw_data, columns=["datetime", "open", "high", "low", "close", "volume"])
            df["datetime"] = pd.to_datetime(df["datetime"], unit="s", errors="coerce")
            df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].apply(
                pd.to_numeric, errors="coerce"
            )
            df.dropna(inplace=True)
            df.sort_values("datetime", inplace=True)
            df.reset_index(drop=True, inplace=True)
            return df
        except Exception as e:
            print("❌ normalize_tpseries_data error:", e)
            return pd.DataFrame()

    def get_tpseries(self, exchange, token, interval="5", start_time=None, end_time=None):
        """
        Fetch raw TPSeries data (historical candles) from ProStocks API.
        'start_time' and 'end_time' should be epoch timestamps (UTC).
        """
        if not self.session_token:
            return {"stat": "Not_Ok", "emsg": "Session token missing. Please login again."}

        # Default → last 60 days
        if start_time is None or end_time is None:
            days_back = 60
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=days_back)
            start_time = int(start_dt.timestamp())
            end_time = int(end_dt.timestamp())

        url = f"{self.base_url}/TPSeries"
        payload = {
            "uid": self.userid,
            "exch": exchange,
            "token": str(token),
            "st": str(start_time),
            "et": str(end_time),
            "intrv": str(interval)
        }

        print("📤 Sending TPSeries Payload:", payload)
        try:
            return self._post_json(url, payload)
        except Exception as e:
            print("❌ Exception in get_tpseries():", e)
            return {"stat": "Not_Ok", "emsg": str(e)}

    def fetch_full_tpseries(self, exchange, token, interval="5", chunk_days=5, max_days=60):
        """
        Fetch full historical TPSeries data in chunks.
        Returns a Pandas DataFrame.
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
            resp = self.get_tpseries(exchange, token, interval, start_time=st, end_time=et)

            if not resp:
                print("⚠️ Empty response, skipping…")
                end_dt = start_dt - timedelta(seconds=1)
                continue

            # --- Handle dict with 'candles' key ---
            if isinstance(resp, dict):
                if "candles" in resp and isinstance(resp["candles"], list):
                    resp = resp["candles"]
                else:
                    print(f"⚠️ TPSeries error: {resp}")
                    end_dt = start_dt - timedelta(seconds=1)
                    time.sleep(0.25)
                    continue

            if not isinstance(resp, list) or len(resp) == 0:
                print("⚠️ Empty chunk. Skipping…")
                end_dt = start_dt - timedelta(seconds=1)
                time.sleep(0.25)
                continue

            df_chunk = self.normalize_tpseries_data(resp)
            if not df_chunk.empty:
                all_chunks.append(df_chunk)

            end_dt = start_dt - timedelta(seconds=1)
            time.sleep(0.25)

        if not all_chunks:
            return pd.DataFrame()

        df = pd.concat(all_chunks, ignore_index=True)
        df.drop_duplicates(subset=["datetime"], inplace=True)
        df.sort_values("datetime", inplace=True)
        return df.reset_index(drop=True)

    def fetch_tpseries_for_watchlist(self, wlname, interval="5"):
        """
        Fetch TPSeries data for all symbols in a given watchlist.
        """
        results = []
        MAX_CALLS_PER_MIN = 20
        call_count = 0

        symbols = self.get_watchlist(wlname)
        if not symbols or "values" not in symbols:
            print("❌ No symbols in watchlist.")
            return []

        for idx, sym in enumerate(symbols["values"]):
            exchange = sym.get("exch", "").strip()
            token = str(sym.get("token", "")).strip()
            symbol = sym.get("tsym", "").strip()

            if not token.isdigit():
                print(f"⚠️ Skipping {symbol}: Invalid token")
                continue

            try:
                print(f"\n📦 {idx+1}. {symbol} → {exchange}|{token}")
                df = self.fetch_full_tpseries(exchange, token, interval)
                if not df.empty:
                    print(f"✅ {symbol}: {len(df)} candles fetched")
                    results.append({"symbol": symbol, "data": df})
                else:
                    print(f"⚠️ {symbol}: No data fetched")
            except Exception as e:
                print(f"❌ {symbol}: Exception {e}")

            call_count += 1
            if call_count >= MAX_CALLS_PER_MIN:
                print("⚠️ TPSeries API limit reached. Stopping.")
                break

        return results

    def start_websocket_for_symbol(self, symbol):
        """
        Start WebSocket to stream live ticks and build candles.
        """
        import websocket, threading

        def on_message(ws, message):
            print("📩 Tick:", message)
            try:
                tick = json.loads(message)
            except Exception as e:
                print("❌ JSON decode error:", e)
                return

            if tick.get("t") != "tk":
                return

            ts = datetime.fromtimestamp(int(tick["ft"]) / 1000)
            minute = ts.replace(second=0, microsecond=0)
            price = float(tick["lp"])
            vol = int(tick.get("v", 1))

            df = st.session_state.get("candles_df", pd.DataFrame())

            if not df.empty and df.iloc[-1]["Datetime"] == minute:
                df.at[df.index[-1], "High"] = max(df.iloc[-1]["High"], price)
                df.at[df.index[-1], "Low"] = min(df.iloc[-1]["Low"], price)
                df.at[df.index[-1], "Close"] = price
                df.at[df.index[-1], "Volume"] += vol
            else:
                new_candle = pd.DataFrame(
                    [[minute, price, price, price, price, vol]],
                    columns=["Datetime", "Open", "High", "Low", "Close", "Volume"]
                )
                df = pd.concat([df, new_candle], ignore_index=True)

            st.session_state["candles_df"] = df
            print("✅ Candle updated:", df.tail(1).to_dict("records"))

        def on_open(ws):
            print("✅ WebSocket connected")
            sub = json.dumps({"t": "t", "k": symbol})
            ws.send(sub)
            print(f"📡 Subscribed to {symbol}")

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

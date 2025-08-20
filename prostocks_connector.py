
# prostocks_connector.py
import os
import time
import json
import hashlib
import requests
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from collections import deque
import threading
import websocket  # pip install websocket-client

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
        # ---- Credentials / Config ----
        self.userid = userid or os.getenv("PROSTOCKS_USER_ID")
        self.password_plain = password_plain or os.getenv("PROSTOCKS_PASSWORD")
        self.vc = vc or os.getenv("PROSTOCKS_VENDOR_CODE")
        self.api_key = api_key or os.getenv("PROSTOCKS_API_KEY")
        self.imei = imei or os.getenv("PROSTOCKS_MAC")
        self.base_url = (base_url or os.getenv("PROSTOCKS_BASE_URL") or "https://starapi.prostocks.com/NorenWClient").rstrip("/")
        self.apkversion = apkversion

        # ---- HTTP session ----
        self.session = requests.Session()
        self.headers = {"Content-Type": "text/plain"}
        self.session_token = None

        # ---- WebSocket state (thread-safe) ----
        self.ws = None
        self.is_ws_connected = False
        self._tick_buffer = deque(maxlen=1000)
        self._live_candles = pd.DataFrame()
        self.is_logged_in = False

        # --- Symbol -> token cache ---
        self._token_cache: dict[str, str] = {}

    # ---------------- Utils ----------------
    @staticmethod
    def sha256(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    # ---------------- Auth ----------------
    def send_otp(self):
        """Triggers OTP (QuickAuth without factor2)."""
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
            "source": "API"
        }

        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            resp = self.session.post(url, data=raw_data, headers=self.headers, timeout=15)
            return resp.json()
        except requests.exceptions.RequestException as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    def login(self, factor2_otp: str):
        """QuickAuth login with OTP; sets self.session_token on success."""
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
            "source": "API"
        }

        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            resp = self.session.post(url, data=raw_data, headers=self.headers, timeout=20)

            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}: {resp.text}"

            data = resp.json()
            if data.get("stat") == "Ok":
                self.session_token = data.get("susertoken")
                self.feed_token = data.get("susertoken")   # ✅ Add this line
                self.userid = data.get("uid", self.userid)
                self.headers["Authorization"] = self.session_token
                self.is_logged_in = True
                print("✅ Login success, session_token & feed_token set:", self.session_token)
                return True, self.session_token

            return False, data.get("emsg", "Login failed")
        except requests.exceptions.RequestException as e:
            return False, f"RequestException: {e}"

    def logout(self):
        """Clear session and mark user as logged out."""
        self.is_logged_in = False
        self.session_token = None
        self.feed_token = None
        print("👋 Logged out successfully")

            # ----------------- Search Scrip -----------------
    def search_scrip(self, tsym, exch="NSE"):
        """
        Search for a symbol in ProStocks.
        tsym: Trading symbol (e.g. 'TATAMOTORS-EQ')
        exch: Exchange ('NSE' or 'BSE')
        Returns: token (str) if found, else None
        """
        try:
            url = f"{self.base_url}/SearchScrip"
            jdata = {
                "uid": self.userid,
                "exch": exch,
                "stext": tsym
            }
            payload = {
                "jData": json.dumps(jdata),
                "jKey": self.jkey
            }

            resp = requests.post(url, data=payload).json()
            # Debug print
            # print("🔍 SearchScrip resp:", resp)

            if resp and resp.get("stat") == "Ok":
                values = resp.get("values", [])
                if values and "token" in values[0]:
                    return values[0]["token"]  # ✅ Return token only
            return None
        except Exception as e:
            print(f"⚠️ search_scrip error: {e}")
            return None

    # ------------- Core POST helper -------------
    def _post_json(self, url, payload):
        if not self.session_token:
            return {"stat": "Not_Ok", "emsg": "Not Logged In. Session Token Missing."}
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}&jKey={self.session_token}"
            resp = self.session.post(url, data=raw_data, headers={"Content-Type": "text/plain"}, timeout=20)
            return resp.json()
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

    def get_token_for_symbol(self, exch: str, tsym: str) -> str | None:
        """
        Resolve tradingsymbol like 'TATAMOTORS-EQ' to numeric token string.
        Caches results to avoid rate limits.
        """
        key = f"{exch}|{tsym}"
        if key in self._token_cache:
            return self._token_cache[key]

        resp = self.search_scrip(tsym, exch=exch)
        try:
            if isinstance(resp, dict) and resp.get("stat") == "Ok":
                values = resp.get("values") or []
                if values:
                    token = str(values[0]["token"])
                    self._token_cache[key] = token
                    return token
            print(f"⚠️ Token resolve failed for {key}: {resp}")
        except Exception as e:
            print(f"❌ get_token_for_symbol error for {key}: {e}")
        return None

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
        if not self.session_token:
            return {"stat": "Not_Ok", "emsg": "Session token missing. Please login again."}

        if st is None or et is None:
            et_dt = datetime.now(timezone.utc)
            st_dt = et_dt - timedelta(days=60)
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
        try:
            return self._post_json(url, payload)
        except Exception as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    def fetch_full_tpseries(self, exch, token, interval="5", chunk_days=5, max_days=60):
        all_chunks = []
        end_dt = datetime.now(timezone.utc)
        start_limit_dt = end_dt - timedelta(days=max_days)

        while end_dt > start_limit_dt:
            start_dt = max(start_limit_dt, end_dt - timedelta(days=chunk_days))
            st = int(start_dt.timestamp())
            et = int(end_dt.timestamp())

            resp = self.get_tpseries(exch, token, interval, st, et)

            if not resp:
                end_dt = start_dt - timedelta(seconds=1)
                time.sleep(0.25)
                continue

            if isinstance(resp, dict):
                if "candles" in resp and isinstance(resp["candles"], list):
                    resp = resp["candles"]
                elif "values" in resp and isinstance(resp["values"], list):
                    resp = resp["values"]
                else:
                    end_dt = start_dt - timedelta(seconds=1)
                    time.sleep(0.25)
                    continue

            if not isinstance(resp, list) or len(resp) == 0:
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
            "ssboe": "epoch",
            "oi": "open_interest"
        }
        df.rename(columns=rename_map, inplace=True)

        if "volume" not in df.columns:
            if "intv" in df.columns:
                df["volume"] = pd.to_numeric(df["intv"], errors="coerce")
            elif "v" in df.columns:
                df["volume"] = pd.to_numeric(df["v"], errors="coerce")

        if "datetime" in df.columns:
            dt_parsed = pd.to_datetime(df["datetime"], format="%d-%m-%Y %H:%M:%S", errors="coerce", dayfirst=True)
            if dt_parsed.isna().any():
                dt_num = pd.to_numeric(df["datetime"], errors="coerce")
                mask = dt_parsed.isna() & dt_num.notna()
                if mask.any():
                    dt_parsed.loc[mask] = pd.to_datetime(dt_num.loc[mask], unit="s", errors="coerce")
            df["datetime"] = dt_parsed

        df = df.dropna(subset=["datetime"])

        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df.dropna(subset=["open", "high", "low", "close"], inplace=True)
        df.sort_values("datetime", inplace=True)
        return df.reset_index(drop=True)

    def fetch_tpseries_for_watchlist(self, wlname, interval="5"):
        results = []
        MAX_CALLS_PER_MIN = 20
        call_count = 0

        symbols = self.get_watchlist(wlname)
        if not symbols or "values" not in symbols:
            return []

        for sym in symbols["values"]:
            exch = sym.get("exch", "").strip()
            token = str(sym.get("token", "")).strip()
            symbol = sym.get("tsym", "").strip()
            if not token.isdigit():
                continue
            try:
                df = self.fetch_full_tpseries(exch, token, interval)
                if not df.empty:
                    results.append({"symbol": symbol, "data": df})
            except Exception:
                pass
            call_count += 1
            if call_count >= MAX_CALLS_PER_MIN:
                break
        return results

           # ------------------ WebSocket (thread-safe buffer) ------------------
    def _on_open(self, ws):
        self.is_ws_connected = True
        print("✅ WebSocket Connected")

    def subscribe_tokens(self, tokens):
        if self.ws and self.is_ws_connected:
            for tk in tokens:
                sub_payload = {"t": "t", "k": tk}
                self.ws.send(json.dumps(sub_payload))
                print("📡 Subscribed:", tk)

    def _on_message(self, ws, message):
        try:
            import streamlit as st
            tick = json.loads(message)
            print("✅ Raw tick received:", tick)   # 👈 Debug add karo
            self._tick_buffer.append(tick)

            # ---- Streamlit live chart ke liye LTP extract ----
            ltp = tick.get("lp") or tick.get("ltp")
            if ltp:
                ts = datetime.now()
                if "live_ticks" not in st.session_state:
                    st.session_state["live_ticks"] = []
                st.session_state["live_ticks"].append({"time": ts, "price": float(ltp)})
                print(f"📈 Tick parsed: time={ts}, price={ltp}")  # 👈 Debug add karo
        except Exception as e:
            print("❌ Tick parse error:", e)

    def _on_error(self, ws, error):
        print("❌ WebSocket Error:", error)

    def _on_close(self, ws, code, msg):
        self.is_ws_connected = False
        print("❌ WebSocket Closed", code, msg)

       # ------------------------------------------------
    # Start WebSocket for multiple symbols
    # ------------------------------------------------
    def start_websocket_for_symbols(self, symbols, interval="1"):
        """
        Start WebSocket and subscribe to given list of symbols.
        Example: api.start_websocket_for_symbols(["TATAMOTORS-EQ", "RELIANCE-EQ"])
        """
        if not self.is_logged_in or not self.feed_token:
            print("❌ Login first before starting WebSocket")
            return

        # Convert symbols into exchange|token list
        token_list = []
        for sym in symbols:
            exch, name = "NSE", sym.replace("-EQ", "")
            token = self.search_scrip(exch, name)   # 👈 search_scrip helper use karna
            if token:
                token_list.append(f"{exch}|{token}")
            else:
                print(f"⚠️ Token not found for {sym}")

        if not token_list:
            print("⚠️ No valid tokens found for symbols")
            return

        def on_open(ws):
            self.is_ws_connected = True
            print("✅ WebSocket Connected")
            sub_data = {"t": "t", "k": "#".join(token_list)}
            try:
                ws.send(json.dumps(sub_data))
                print(f"📡 Subscribed: {token_list}")
            except Exception as e:
                print("❌ Subscribe error:", e)

        def on_message(ws, message):
            try:
                tick = json.loads(message)
                self._tick_buffer.append(tick)  # 👈 store in buffer
                self.on_tick(tick)              # optional handler
            except Exception as e:
                print("⚠️ Tick parse error:", e)

        def on_close(ws, code, reason):
            self.is_ws_connected = False
            print(f"❌ WebSocket closed: {code}, {reason}")

        def on_error(ws, error):
            print(f"⚠️ WebSocket error: {error}")

        # Actual websocket URL (ProStocks)
        ws_url = f"wss://starapi.prostocks.com/NorenWSTP/?u={self.userid}&t={self.feed_token}&uid={self.userid}"
        print(f"🔗 Connecting to WebSocket: {ws_url}")

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )

        # Run websocket in background thread
        self.wst = threading.Thread(target=self.ws.run_forever, kwargs={"ping_interval": 30}, daemon=True)
        self.wst.start()

    # ------------------------------------------------
    # Start WebSocket for single symbol
    # ------------------------------------------------
    def start_websocket_for_symbol(self, symbol):
        self.start_websocket_for_symbols([symbol])

    # ------------------------------------------------
    # Stop WebSocket
    # ------------------------------------------------
    def stop_websocket(self):
        try:
            if self.ws:
                self.ws.close()
                print("🛑 WebSocket stopped")
        except Exception as e:
            print("❌ stop_websocket error:", e)

    # ------------------------------------------------
    # Get latest ticks from buffer
    # ------------------------------------------------
    def get_latest_ticks(self, n=20):
        return list(self._tick_buffer)[-n:]

def build_live_candles(self, interval="1min"):
    """Convert buffered ticks into minute candles."""
    ticks = list(self._tick_buffer)
    print(f"🕐 build_live_candles called, total ticks={len(ticks)}")  # 👈 Debug add karo

    if not ticks:
        return self._live_candles

    rows = []
    for tick in ticks:
        # Accept any tick that has a last price
        if "lp" not in tick and "ltp" not in tick:
            continue

        # Timestamp: 'ft' (feed time, ms) preferred; fallback to now()
        if "ft" in tick:
            try:
                ts = datetime.fromtimestamp(int(tick["ft"]) / 1000)
            except Exception:
                ts = datetime.now()
        else:
            ts = datetime.now()

        minute = ts.replace(second=0, microsecond=0)
        price = float(tick.get("lp") or tick.get("ltp") or 0)
        vol = int(tick.get("v", 1))
        rows.append([minute, price, price, price, price, vol])

    if not rows:
        return self._live_candles

    df_new = pd.DataFrame(rows, columns=["Datetime", "Open", "High", "Low", "Close", "Volume"])
    if self._live_candles.empty:
        self._live_candles = df_new
    else:
        self._live_candles = (
            pd.concat([self._live_candles, df_new], ignore_index=True)
            .drop_duplicates(subset=["Datetime"], keep="last")
        )
    return self._live_candles.sort_values("Datetime")


# ---------------- Chart Helper ----------------
def show_combined_chart(self, df_hist, interval="1min", refresh=10):
    import plotly.graph_objects as go
    df_hist = df_hist.copy()
    fig = go.Figure()

    def update_chart():
        df_live = self.build_live_candles(interval)
        df_all = pd.concat([df_hist, df_live], ignore_index=True).drop_duplicates(
            subset=["datetime", "Datetime"], keep="last"
        )
        if "Datetime" in df_all.columns:
            df_all["datetime"] = df_all["Datetime"]

        fig.data = []
        fig.add_trace(go.Candlestick(
            x=df_all["datetime"],
            open=df_all["open"] if "open" in df_all else df_all["Open"],
            high=df_all["high"] if "high" in df_all else df_all["High"],
            low=df_all["low"] if "low" in df_all else df_all["Low"],
            close=df_all["close"] if "close" in df_all else df_all["Close"],
            name="Candles"
        ))
        fig.update_layout(
            title="Historical + Live Candles",
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            height=600,
        )
        fig.show()

    print("📊 Live chart running... (close chart window to stop)")
    try:
        while True:
            update_chart()
            time.sleep(refresh)
    except KeyboardInterrupt:
        print("🛑 Chart stopped")




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
from NorenApiPy import NorenApi


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
        self.jkey = None   # 👈 yaha add karo

        # ---- WebSocket state (thread-safe) ----
        self.jkey = None
        self.feed_token = None
        self.ws = None
        self.wst = None
        self.is_ws_connected = False
        self._tick_buffer = deque(maxlen=1000)
        self._live_candles = pd.DataFrame()
        self.subscribed_tokens = []

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
        Returns: 'EXCH|TOKEN' string if found, else None
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
            if resp and resp.get("stat") == "Ok":
                values = resp.get("values", [])
                if values and "token" in values[0]:
                    token = values[0]["token"]
                    return f"{exch}|{token}"   # ✅ Return proper format
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
            resp = self.session.post(url, data=raw_data,
                                     headers={"Content-Type": "text/plain"},
                                     timeout=20)
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

    def get_tokens_from_watchlist(self, wlname):
        """Fetch tokens for all symbols in a given watchlist"""
        wl_data = self.get_watchlist(wlname)
        tokens = []
        symbols = []

        if isinstance(wl_data, dict):
            scrips = wl_data.get("values", [])
        elif isinstance(wl_data, list):
            scrips = wl_data
        else:
            scrips = []

        for scrip in scrips:
            if not isinstance(scrip, dict):
                continue
            exch = scrip.get("exch") or scrip.get("exchange")
            token = scrip.get("token")
            tsym = scrip.get("tsym") or scrip.get("symbol")
            if exch and token and tsym:
                tokens.append(f"{exch}|{token}")
                symbols.append(tsym)
        return tokens, symbols

    def get_token_for_symbol(self, exch: str, tsym: str) -> str | None:
        """
        Resolve tradingsymbol like 'TATAMOTORS-EQ' to numeric token string.
        Returns: 'EXCH|TOKEN' format (same as search_scrip).
        Uses cache to avoid repeated lookups.
        """
        key = f"{exch}|{tsym}"
        if key in self._token_cache:
            return self._token_cache[key]

        token_str = self.search_scrip(tsym, exch=exch)  # already returns 'EXCH|TOKEN'
        if token_str:
            self._token_cache[key] = token_str
            return token_str

        print(f"⚠️ Token resolve failed for {exch}|{tsym}")
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
        """
        Subscribe tokens to WebSocket
        tokens: list of "EXCH|TOKEN"
        """
        if not self.ws:
            print("⚠️ WebSocket not connected.")
            return

        try:
            for tk in self._sub_tokens:
                sub_req = {"t": "t", "k": tk}
                ws.send(json.dumps(sub_req))
                print(f"📡 Subscribed: {sub_req}")
        except Exception as e:
            print("❌ Subscription error:", e)

    def _on_message(self, ws, message):
        try:
            import streamlit as st
            tick = json.loads(message)
            print("✅ Raw tick received:", tick)
            self._tick_buffer.append(tick)

            # ---- Streamlit live chart ke liye LTP extract ----
            ltp = tick.get("lp") or tick.get("ltp")
            if ltp:
                ts = datetime.now()
                if "live_ticks" not in st.session_state:
                    st.session_state["live_ticks"] = []
                st.session_state["live_ticks"].append({"time": ts, "price": float(ltp)})
                print(f"📈 Tick parsed: time={ts}, price={ltp}")
        except Exception as e:
            print("❌ Tick parse error:", e)

    def _on_error(self, ws, error):
        print("❌ WebSocket Error:", error)

    def _on_close(self, ws, code, msg):
        self.is_ws_connected = False
        print("❌ WebSocket Closed", code, msg)

    # ==========================
    # WebSocket: Subscribe to multiple symbols
    # ==========================
    def start_websocket_for_symbols(self, symbols):
        """
        Starts WebSocket and subscribes to live ticks for given symbols.
        symbols: list of dicts with { 'exch': 'NSE', 'token': '22' }
        Example: [{"exch":"NSE", "token":"11872"}, {"exch":"NSE", "token":"3045"}]
        """
        if not symbols or not isinstance(symbols, list):
            print("⚠️ No symbols provided for WebSocket subscription")
            return

        subs = [f"{s['exch']}|{s['token']}" for s in symbols if 'exch' in s and 'token' in s]
        if not subs:
            print("⚠️ No valid tokens found for subscription")
            return

        self.subscribed_tokens = subs
        self._sub_tokens = subs  # for later use

        # --- WebSocket Callbacks ---
        def on_open(ws):
            self.is_ws_connected = True
            print("✅ WebSocket Connected")

            try:
                sub_key = "#".join(self._sub_tokens)   # join multiple tokens
                sub_req = {"t": "t", "k": sub_key}
                ws.send(json.dumps(sub_req))
                print(f"📡 Sent subscription for {token}")          
            except Exception as e:
                print("❌ Subscription error:", e)

        def on_message(ws, message):
            try:
                data = json.loads(message)
                print("📥 Server Msg:", data)

                if data.get("t") == "tk":   # tick packet
                    self._tick_buffer.append(data)
                    print(f"✅ Tick: {data.get('tk')} LTP={data.get('lp')}")
                elif data.get("t") == "ck" and data.get("stat") == "Ok":  # subscription ack
                    print(f"✅ Subscription confirmed for {data.get('k')}: {data}")
                elif data.get("t") == "e":    # error from server
                    print("❌ Subscription error:", data)
                else:
                    print("ℹ️ Other Msg:", data)

            except Exception as e:
                print("⚠️ Tick parse error:", e)

        def on_error(ws, error):
            print("⚠️ WebSocket Error:", error)

        def on_close(ws, close_status_code, close_msg):
            self.is_ws_connected = False
            print("❌ WebSocket Closed:", close_status_code, close_msg)

        # --- Heartbeat Thread ---
        def send_ping(ws):
            while True:
                if self.is_ws_connected:
                    try:
                        ws.send(json.dumps({"t": "h"}))
                    except Exception as e:
                        print("⚠️ Ping error:", e)
                time.sleep(30)

        ws_url = f"wss://starapi.prostocks.com/NorenWSTP/?u={self.userid}&t={self.feed_token}&uid={self.userid}"
        print(f"🔗 Connecting to WebSocket: {ws_url}")

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        # Start heartbeat
        threading.Thread(target=send_ping, args=(self.ws,), daemon=True).start()

        # Run WebSocket in a background thread
        self.wst = threading.Thread(
            target=self.ws.run_forever,
            kwargs={"ping_interval": 30, "ping_timeout": 10},
            daemon=True,
        )
        self.wst.start()

    # ==========================
    # Start WebSocket for single symbol
    # ==========================
    def start_websocket_for_symbol(self, symbol):
        self.start_websocket_for_symbols([symbol])

    # ==========================
    # Stop WebSocket
    # ==========================
    def stop_websocket(self):
        try:
            if self.ws:
                self.ws.close()
                print("🛑 WebSocket stopped")
        except Exception as e:
            print("❌ stop_websocket error:", e)

    # ==========================
    # Get latest ticks from buffer
    # ==========================
    def get_latest_ticks(self, n=20):
        return list(self._tick_buffer)[-n:]

    # ==========================
    # Tick handler
    # ==========================
    def on_tick(self, tick):
        import streamlit as st
        try:
            ltp = tick.get("lp") or tick.get("ltp")
            if ltp:
                ts = pd.Timestamp.now()
                if "live_ticks" not in st.session_state:
                    st.session_state["live_ticks"] = []
                st.session_state["live_ticks"].append({"time": ts, "price": float(ltp)})
                print(f"📈 Tick: {ts} -> {ltp}")
            self._tick_buffer.append(tick)
        except Exception as e:
            print("❌ Tick handler error:", e)

    # ==========================
    # Build live candles
    # ==========================
    def build_live_candles(self, interval="1min"):
        ticks = list(self._tick_buffer)
        print(f"🕐 build_live_candles called, total ticks={len(ticks)}")

        if not ticks:
            return self._live_candles

        rows = []
        for tick in ticks:
            try:
                ts = datetime.fromtimestamp(int(tick.get("ft", time.time() * 1000)) / 1000)
            except:
                ts = datetime.now()
            minute = ts.replace(second=0, microsecond=0)
            price = float(tick.get("lp") or tick.get("ltp") or 0)
            vol = int(tick.get("v", 0))
            rows.append([minute, price, vol])

        df_new = pd.DataFrame(rows, columns=["Datetime", "Price", "Volume"])
        if df_new.empty:
            return self._live_candles

        agg = df_new.groupby("Datetime").agg(
            Open=("Price", "first"),
            High=("Price", "max"),
            Low=("Price", "min"),
            Close=("Price", "last"),
            Volume=("Volume", "sum"),
        ).reset_index()

        if self._live_candles.empty:
            self._live_candles = agg
        else:
            self._live_candles = (
                pd.concat([self._live_candles, agg], ignore_index=True)
                .drop_duplicates(subset=["Datetime"], keep="last")
                .sort_values("Datetime")
            )
        return self._live_candles

    # ==========================
    # Chart Helper
    # ==========================
    def show_combined_chart(self, df_hist, interval="1min", refresh=10):
        import plotly.graph_objects as go

        df_hist = df_hist.copy()
        fig = go.Figure()

        def update_chart():
            df_live = self.build_live_candles(interval)
            df_all = pd.concat([df_hist, df_live], ignore_index=True)
            df_all = df_all.drop_duplicates(subset=["Datetime"], keep="last")
            df_all = df_all.sort_values("Datetime")

            fig.data = []
            fig.add_trace(
                go.Candlestick(
                    x=df_all["Datetime"],
                    open=df_all["Open"],
                    high=df_all["High"],
                    low=df_all["Low"],
                    close=df_all["Close"],
                    name="Candles",
                )
            )
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













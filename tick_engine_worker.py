
    #!/usr/bin/env python3
"""
LIVE TICK ENGINE
----------------
✔ Fetch TPSeries (60 days)
✔ Subscribe WS ticks for all tokens
✔ Build LIVE candles (1m/3m/5m)
✔ Merge TPSeries + live candle
✔ Save final dataframe per symbol
✔ Accessible to Auto Trader Worker
"""

import asyncio
import json
import os
import time
from datetime import datetime
import pandas as pd
import pytz
import requests

from prostocks_connector import ProStocksAPI

BACKEND_URL = os.environ.get("BACKEND_URL", "https://backend-stream-nmlf.onrender.com")

SAVE_PATH = "/tmp/live_candles"
os.makedirs(SAVE_PATH, exist_ok=True)

IST = pytz.timezone("Asia/Kolkata")


# -----------------------------------------------------------
# 1) Load full TPSeries 60 days (or as per API)
# -----------------------------------------------------------
def load_backfill(ps_api, exch, token, interval="1"):
    df = ps_api.fetch_full_tpseries(exch, token, interval)
    if df is None or isinstance(df, dict) or df.empty:
        return pd.DataFrame()

    df["datetime"] = pd.to_datetime(df["datetime"])
    if df["datetime"].dt.tz is None:
        df["datetime"] = df["datetime"].dt.tz_localize(IST)
    else:
        df["datetime"] = df["datetime"].dt.tz_convert(IST)

    df = df.sort_values("datetime")
    return df


# -----------------------------------------------------------
# 2) Build LIVE candles from ticks
# -----------------------------------------------------------
class CandleBuilder:
    def __init__(self):
        # key = (symbol, minute)
        self.candles = {}

    def update_tick(self, symbol, ltp, volume, ts):
        ts = datetime.fromtimestamp(ts, tz=IST)
        minute = ts.replace(second=0, microsecond=0)

        key = (symbol, minute)

        if key not in self.candles:
            self.candles[key] = {
                "datetime": minute,
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "volume": volume
            }
        else:
            c = self.candles[key]
            c["high"] = max(c["high"], ltp)
            c["low"] = min(c["low"], ltp)
            c["close"] = ltp
            c["volume"] += volume

    def get_latest(self, symbol):
        latest_keys = [k for k in self.candles.keys() if k[0] == symbol]
        if not latest_keys:
            return None

        latest_key = sorted(latest_keys, key=lambda x: x[1])[-1]
        return self.candles[latest_key]


candle_builder = CandleBuilder()


# -----------------------------------------------------------
# 3) Merge TPSeries + LIVE candle
# -----------------------------------------------------------
def merge_candles(df_tp, live_candle):
    df = df_tp.copy()

    if live_candle:
        # last TPSeries candle हटा कर latest live candle जोड़ते हैं
        df = df[df["datetime"] < live_candle["datetime"]]
        df = pd.concat([df, pd.DataFrame([live_candle])], ignore_index=True)

    return df


# -----------------------------------------------------------
# 4) WebSocket loop – PS API WS + merge + save
# -----------------------------------------------------------
async def ws_loop(ps_api, token_map):
    """
    Start the PS API websocket using the PS API's start_ticks helper and
    receive ticks via the ps_api._on_tick callback.
    token_map: { "TSYM-EQ": "21614", ... }
    """
    tokens = [f"NSE|{t}" for t in token_map.values()]

    global cached_tp
    last_merge = time.time()
    print("🚀 on_tick function registered")
    
    def on_tick(payload):
        print("📡 TICK RECEIVED:", payload)
        try:
            if isinstance(payload, str):
                data = json.loads(payload)
            else:
                data = payload

            token = data.get("tk") or data.get("token")
            ltp = data.get("lp") or data.get("ltp")
            vol = data.get("v") or data.get("vol") or 0
            ts = data.get("ft") or data.get("time") or data.get("timestamp")

            if token is None or ltp in (None, "", "NA"):
                return

            try:
                ltp = float(ltp)
            except:
                return
            try:
                vol = int(vol)
            except:
                vol = 0
            try:
                ts = int(ts)
            except:
                try:
                    ts = int(float(ts) / 1000)
                except:
                    ts = int(time.time())

            # token → tsym map
            tsym = None
            for s, t in token_map.items():
                if str(t) == str(token):
                    tsym = s
                    break
            if tsym is None:
                return

            candle_builder.update_tick(tsym, ltp, vol, ts)

        except Exception as e:
            print("on_tick error:", e)

    ps_api._on_tick = on_tick

    try:
        ps_api.start_ticks(tokens)
        print(f"✔ Started PS websocket with {len(tokens)} tokens")
        ps_api.is_ws_connected = True
    except Exception as e:
        print("❌ Failed to start PS websocket:", e)
        ps_api.is_ws_connected = False
        return

    try:
        while True:
            if time.time() - last_merge > 3:
                last_merge = time.time()
                for sym, tkn in token_map.items():
                    fn = os.path.join(SAVE_PATH, f"{sym}.json")

                    df_tp = cached_tp.get(sym)
                    live_c = candle_builder.get_latest(sym)

                    try:
                        if df_tp is not None:
                            df_final = merge_candles(df_tp, live_c)
                        elif live_c:
                            df_final = pd.DataFrame([live_c])
                        else:
                            df_final = pd.DataFrame()

                        if not df_final.empty:
                            df_final.to_json(fn, orient="records", date_format="iso")
                    except Exception as e:
                        print(f"⚠️ Error saving {sym}: {e}")

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        print("ws_loop cancelled")
    except Exception as e:
        print("WS loop error:", e)
    finally:
        print("WS loop exiting")


# -----------------------------------------------------------
# 5) ENTRY POINT
# -----------------------------------------------------------
if __name__ == "__main__":

    # ---- 1) Load session + tokens from backend ----
    print("🔍 Fetching session_info from backend...")
    try:
        resp = requests.get(f"{BACKEND_URL}/session_info", timeout=5)
        session_info = resp.json()
    except Exception as e:
        print("❌ Could not load session_info from backend:", e)
        exit(1)

    session_token = session_info.get("session_token")
    token_map = session_info.get("tokens_map", {})
    userid = session_info.get("userid")

    if not session_token or not token_map or not userid:
        print("❌ No session or tokens or userid from backend — cannot continue.")
        print("👉 Fix: Tab-3 open karke watchlist load karo, phir Tab-4 se backend /init run karo.")
        exit(1)

    print(f"✔ Session OK, userid={userid}, tokens={len(token_map)}")

    # ---- 2) Create ps_api WITHOUT login (reuse backend session) ----
    base_url = os.environ.get(
        "BASE_URL",
        "https://starapi.prostocks.com/NorenWClientTP"
    )

    ps_api = ProStocksAPI(
        userid=userid,
        password_plain="",
        vc=os.environ.get("VC"),
        api_key=os.environ.get("API_KEY"),
        imei=os.environ.get("IMEI"),
        base_url=base_url
    )

    # Inject backend session
    ps_api.session_token = session_token
    ps_api.jKey = session_token
    ps_api.uid = userid
    ps_api.actid = userid
    ps_api.logged_in = True
    ps_api.is_logged_in = True
    ps_api.is_session_active = True

    ps_api.headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": session_token
    }

    print("✔ Backend session attached. Loading TPSeries…")

    # ---- 3) Preload TPSeries for all symbols ----
    cached_tp = {}
    for sym, tkn in token_map.items():
        try:
            df = load_backfill(ps_api, "NSE", tkn, "1")
            cached_tp[sym] = df
        except Exception as e:
            print(f"⚠️ Backfill failed for {sym}: {e}")
            cached_tp[sym] = pd.DataFrame()

    print("✔ TPSeries cached. Starting WS…")

    # ---- 4) Run WS loop forever ----
    asyncio.run(ws_loop(ps_api, token_map))


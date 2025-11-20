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
from datetime import datetime, timedelta
import pandas as pd
import pytz
from prostocks_connector import ProStocksAPI

import requests

BACKEND_URL = os.environ.get("BACKEND_URL", "https://backend-stream-nmlf.onrender.com")

# fetch tokens_map from backend
try:
    resp = requests.get(f"{BACKEND_URL}/tokens", timeout=5)
    token_map = resp.json().get("tokens_map", {})
    print(f"✔ Loaded {len(token_map)} tokens from backend")
except Exception as e:
    print("❌ Could not load token_map from backend:", e)
    token_map = {}

SAVE_PATH = "/tmp/live_candles"
os.makedirs(SAVE_PATH, exist_ok=True)

IST = pytz.timezone("Asia/Kolkata")


# -----------------------------------------------------------
# 1) Load full TPSeries 60 days
# -----------------------------------------------------------
def load_backfill(ps_api, exch, token, interval="1"):
    df = ps_api.fetch_full_tpseries(exch, token, interval)
    if df is None or isinstance(df, dict) or df.empty:
        return pd.DataFrame()

    df["datetime"] = pd.to_datetime(df["datetime"]).dt.tz_localize(IST)
    df = df.sort_values("datetime")
    return df


# -----------------------------------------------------------
# 2) Build LIVE candles from ticks
# -----------------------------------------------------------
class CandleBuilder:
    def __init__(self):
        self.candles = {}  # {symbol: { "open": ..., "high": ..., } }

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
        df = df[df["datetime"] < live_candle["datetime"]]  # remove last tpseries candle
        df = pd.concat([df, pd.DataFrame([live_candle])], ignore_index=True)

    return df


# ---------------------- Paste replacement for ws_loop + __main__ section ----------------------

async def ws_loop(ps_api, token_map):
    """
    Start the PS API websocket using the PS API's start_ticks helper and
    receive ticks via the ps_api._on_tick callback.
    token_map: { "TSYM-EQ": "21614", ... }
    """
    # Build tokens in the format expected by ProStocks WS (NSE|token)
    tokens = [f"NSE|{t}" for t in token_map.values()]

    # Ensure cached_tp exists globally
    global cached_tp
    last_merge = time.time()

    # on_tick will be invoked from ps_api's WS thread
    def on_tick(payload):
        try:
            # payload may already be parsed dict; guard both types
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

            # normalize numeric types
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
                # sometimes timestamp is in ms string
                try:
                    ts = int(float(ts) / 1000)
                except:
                    ts = int(time.time())

            # find tsym from token_map
            tsym = None
            for s, t in token_map.items():
                if str(t) == str(token):
                    tsym = s
                    break
            if tsym is None:
                return

            # update builder
            candle_builder.update_tick(tsym, ltp, vol, ts)

        except Exception as e:
            print("on_tick error:", e)

    # assign the callback into ps_api (consumed by its WS implementation)
    ps_api._on_tick = on_tick

    # start the PS websocket (assumes implementation starts a thread and delivers to _on_tick)
    try:
        ps_api.start_ticks(tokens)
        print(f"✔ Started PS websocket with {len(tokens)} tokens")
        ps_api.is_ws_connected = True
    except Exception as e:
        print("❌ Failed to start PS websocket:", e)
        ps_api.is_ws_connected = False
        return

    # background merge loop — only IO here (non-blocking)
    try:
        while True:
            # merge + save every 3 seconds
            if time.time() - last_merge > 3:
                last_merge = time.time()
                for sym, tkn in token_map.items():
                    fn = os.path.join(SAVE_PATH, f"{sym}.json")

                    df_tp = cached_tp.get(sym)
                    live_c = candle_builder.get_latest(sym)

                    try:
                        df_final = merge_candles(df_tp, live_c) if df_tp is not None else (pd.DataFrame([live_c]) if live_c else pd.DataFrame())
                        # Save only when not empty
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


if __name__ == "__main__":

    # ---- 1) Load session + tokens from backend ----
    print("🔍 Fetching session_info from backend...")
    session_info = requests.get(f"{BACKEND_URL}/session_info", timeout=5).json()

    session_token = session_info.get("session_token")
    token_map = session_info.get("tokens_map", {})
    userid = session_info.get("userid")   # ❗ Add this in backend

    if not session_token or not token_map or not userid:
        print("❌ No session or tokens or userid from backend — cannot continue.")
        exit(1)

    # Create ps_api WITHOUT LOGIN (reuse backend session)
    ps_api = ProStocksAPI(
        userid=userid,
        password_plain="",
        vc=os.environ.get("VC"),
        api_key=os.environ.get("API_KEY"),
        imei=os.environ.get("IMEI"),
        base_url=os.environ.get("BASE_URL")
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

    # Preload TPSeries...
    cached_tp = {}
    for sym, tkn in token_map.items():
        try:
            df = load_backfill(ps_api, "NSE", tkn, "1")
            cached_tp[sym] = df
        except Exception as e:
            print(f"⚠️ Backfill failed for {sym}: {e}")
            cached_tp[sym] = pd.DataFrame()

    print("✔ TPSeries cached. Starting WS…")

    asyncio.run(ws_loop(ps_api, token_map))


    # ----------------------------
    # Prefer backend-synced tokens_map (sent via /init)
    # Fallback to get_watchlists() only if tokens_map missing
    # ----------------------------

    # ---- HARD STOP ----
    if not token_map:
        print("❌ No tokens received from backend — cannot continue.")
        print("👉 Fix: Open Streamlit Tab-3 → load watchlist → backend /init will send tokens_map.")
        exit(1)

    print(f"✔ Using backend tokens_map: {len(token_map)} symbols")

    # Preload TPSeries 60 days into cached_tp
    cached_tp = {}
    for sym, tkn in token_map.items():
        try:
            df = load_backfill(ps_api, "NSE", tkn, "1")
            cached_tp[sym] = df
        except Exception as e:
            print(f"⚠️ Backfill failed for {sym}: {e}")
            cached_tp[sym] = pd.DataFrame()

    print("✔ TPSeries cached. Starting WS…")

    # Run the ws_loop forever
    asyncio.run(ws_loop(ps_api, token_map))

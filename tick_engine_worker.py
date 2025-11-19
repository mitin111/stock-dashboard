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


# -----------------------------------------------------------
# 4) MAIN — WS ticker to candle builder
# -----------------------------------------------------------
async def ws_loop(ps_api, token_map):
    ws = ps_api.connect_websocket(
        tokens=[f"NSE|{t}" for t in token_map.values()],
        on_tick=None
    )

    last_merge = time.time()

    while True:
        try:
            tick = ws.recv()  # raw ws message
            if not tick:
                continue

            data = json.loads(tick)
            token = data.get("tk")
            ltp = float(data.get("lp", 0))
            vol = int(data.get("v", 0))
            ts = int(data.get("ft", 0))

            # Find symbol from token
            symbol = None
            for s, t in token_map.items():
                if str(t) == str(token):
                    symbol = s
                    break

            if not symbol:
                continue

            # Update live candle
            candle_builder.update_tick(symbol, ltp, vol, ts)

            # Every 3 sec → merge + save DF
            if time.time() - last_merge > 3:
                last_merge = time.time()
                for sym, tkn in token_map.items():
                    fn = os.path.join(SAVE_PATH, f"{sym}.json")

                    # Load cached TPSeries (preloaded)
                    df_tp = cached_tp[sym]

                    live_c = candle_builder.get_latest(sym)

                    df_final = merge_candles(df_tp, live_c)

                    df_final.to_json(
                        fn,
                        orient="records",
                        date_format="iso"
                    )

        except Exception as e:
            print("WS Error:", e)
            await asyncio.sleep(1)


# -----------------------------------------------------------
# 5) Entry point
# -----------------------------------------------------------
if __name__ == "__main__":
    creds = {
        "uid": os.environ.get("UID"),
        "pwd": os.environ.get("PWD"),
        "vc": os.environ.get("VC"),
        "api_key": os.environ.get("API_KEY"),
        "imei": os.environ.get("IMEI"),
        "base_url": os.environ.get("BASE_URL")
    }

    ps_api = ProStocksAPI(
        userid=creds["uid"],
        password_plain=creds["pwd"],
        vc=creds["vc"],
        api_key=creds["api_key"],
        imei=creds["imei"],
        base_url=creds["base_url"]
    )

    print("✔ Logged in. Loading TPSeries…")

    # Load watchlists → load tokens
    all_syms = []
    for wl in ps_api.get_watchlists().get("values", []):
        data = ps_api.get_watchlist(wl).get("values", [])
        for s in data:
            all_syms.append((s["tsym"], s["token"]))

    token_map = {sym: tkn for sym, tkn in all_syms}

    print(f"✔ Loaded {len(token_map)} symbols")

    # Preload TPSeries 60 days
    cached_tp = {}
    for sym, tkn in token_map.items():
        cached_tp[sym] = load_backfill(ps_api, "NSE", tkn, "1")

    print("✔ TPSeries cached. Starting WS…")

    asyncio.run(ws_loop(ps_api, token_map))

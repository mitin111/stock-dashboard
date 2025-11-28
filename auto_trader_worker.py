#!/usr/bin/env python3
"""
AUTO TRADER WORKER (LIVE 5-MIN CANDLES)
---------------------------------------
✔ Reads merged live candles from tick_engine_worker.py
✔ Applies indicators on REAL-TIME data
✔ TRM + MACD + PAC strategy
✔ Hammer exit monitor
✔ Trailing SL updater
✔ Order placement via ProStocks API
✔ Runs 24/7 — even if Dashboard is closed
"""

import os
import time
import json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pytz

from prostocks_connector import ProStocksAPI
import tkp_trm_chart as trm
from batch_screener import (
    generate_signal_for_df,
    place_order_from_signal,
    resp_to_status_and_list
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CANDLE_PATH = os.path.join(BASE_DIR, "live_candles")

print("📁 Auto trader candle path:", CANDLE_PATH)


IST = pytz.timezone("Asia/Kolkata")

# =====================================================================
#  🔥 READ MERGED LIVE CANDLE (5-MIN)
# =====================================================================
def load_live_5min_candle(sym):
    """Load latest REAL-TIME merged 5m candle from JSON produced by tick_engine."""
    sym = sym.replace("-EQ", "").replace(".NS","").strip().upper()
    fn = os.path.join(CANDLE_PATH, f"{sym}.json")
    if not os.path.exists(fn):
        return pd.DataFrame()

    try:
        df = pd.read_json(fn)
        if df.empty:
            return df

        df["datetime"] = pd.to_datetime(df["datetime"]).dt.tz_convert(IST)
        df = df.sort_values("datetime").reset_index(drop=True)

        # Make 5-minute timeframe
        df["bucket"] = df["datetime"].dt.floor("5min")
        df5 = df.groupby("bucket").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum")
        ).reset_index()

        df5 = df5.rename(columns={"bucket": "datetime"})
        return df5.tail(200)  # last 200 candles

    except Exception as e:
        print(f"⚠️ Failed reading {sym}.json →", e)
        return pd.DataFrame()


# =====================================================================
#  🔥 AUTO TRADE SINGLE SYMBOL
# =====================================================================
def process_live_symbol(ps_api, sym, settings):
    df = load_live_5min_candle(sym)

    if df.empty or len(df) < 20:
        return {"symbol": sym, "status": "no_data"}

    # --- apply strategy indicators (exact chart logic) ---
    sig = generate_signal_for_df(df, settings)
    if sig is None:
        return {"symbol": sym, "status": "no_signal"}

    # --- place order if signal valid ---
    # --- place order if signal valid (via BACKEND) ---
    if sig.get("signal") in ["BUY", "SELL"]:

        import requests

        order_resp = requests.post(
            "https://backend-stream-nmlf.onrender.com/place_order",
            json={
                "symbol": sym,
                "side": sig["signal"],
                "qty": sig.get("suggested_qty", 1)
            },
            timeout=5
        ).json()

        return {"symbol": sym, "status": "order", "resp": order_resp}

        return {"symbol": sym, "status": "neutral"}


# =====================================================================
#  🔥 MAIN AUTO TRADER LOOP (CONTINUOUS)
# =====================================================================
def auto_trade_loop(ps_api, settings, symbols):
    # wait until at least one file exists for first symbol (max 30s)
    timeout = time.time() + 30
    while time.time() < timeout:
        sample_fn = os.path.join(CANDLE_PATH, f"{symbols[0]}.json")
        if os.path.exists(sample_fn) and os.path.getsize(sample_fn) > 100:
            break
        print("Waiting for merged candle files from tick engine...")
        time.sleep(1) 

    print(f"🚀 Auto Trader started for {len(symbols)} symbols (5-minute LIVE mode)")
    print("Waiting for next 5-minute candle...")

    last_trade_minute = None

    while True:
        try:
            now = datetime.now(IST)
            current_min = now.minute - (now.minute % 5)

            if last_trade_minute != current_min:   # new 5m candle
                last_trade_minute = current_min
                print(f"\n🕒 NEW 5-MIN CANDLE @ {now.strftime('%H:%M')} — running strategy...\n")

                for sym in symbols:
                    try:
                        res = process_live_symbol(ps_api, sym, settings)
                        print("→", sym, res)
                    except Exception as e:
                        print(f"❌ Error processing {sym}:", e)

            time.sleep(2)

        except Exception as e:
            print("⚠️ Auto Trader Loop Error:", e)
            time.sleep(2)


# =====================================================================
#  🔥 ENTRY POINT
# =====================================================================
if __name__ == "__main__":

    import requests   # ✅ VERY IMPORTANT
    
    print("🔍 Fetching session_info from backend...")
    resp = requests.get("https://backend-stream-nmlf.onrender.com/session_info", timeout=10)
    session_info = resp.json()

    if not session_info.get("session_token"):
        print("❌ No session in backend. Login first from Dashboard.")
        exit(1)

    print("✅ Backend session found for:", session_info["userid"])

    ps_api = ProStocksAPI(
        userid=session_info["userid"],
        password_plain="",  # ✅ Not needed (already logged in)
        vc=session_info.get("vc"),
        api_key=session_info.get("api_key"),
        imei=session_info.get("imei"),
        base_url=os.getenv("PROSTOCKS_BASE_URL", "https://starapi.prostocks.com/NorenWClientTP")
    )

    # Inject same session
    ps_api.session_token = session_info["session_token"]
    ps_api.jKey = session_info["session_token"]
    ps_api.uid = session_info["userid"]
    ps_api.actid = session_info["userid"]

    ps_api.logged_in = True
    ps_api.is_logged_in = True
    ps_api.is_session_active = True
    ps_api.login_status = True

    print("✅ Using backend cloned session")
    print("✔ Logged in. Loading watchlists...")


    # Load all symbols from watchlists
    all_syms = []
    wls = ps_api.get_watchlists().get("values", [])

    for wl in wls:
        data = ps_api.get_watchlist(wl)
        if data.get("stat") == "Ok":
            for s in data["values"]:
                all_syms.append(s["tsym"])

    symbols = sorted(list(set(all_syms)))

    print("✔ Symbols loaded:", len(symbols))

    # Load TRM settings
    try:
        from tkp_trm_chart import get_trm_settings_safe
        settings = get_trm_settings_safe()
    except:
        print("❌ Could not load TRM settings")
        exit(1)

    print("✔ TRM settings loaded")

    # Start Auto Trader loop
    auto_trade_loop(ps_api, settings, symbols)

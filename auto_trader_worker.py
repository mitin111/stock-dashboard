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
    resp_to_status_and_list,
    monitor_open_positions
)

CANDLE_PATH = "/tmp/live_candles"
IST = pytz.timezone("Asia/Kolkata")

# =====================================================================
#  🔥 READ MERGED LIVE CANDLE (5-MIN)
# =====================================================================
def load_live_5min_candle(sym):
    """Load latest REAL-TIME merged 5m candle from JSON produced by tick_engine."""
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
    if sig.get("signal") in ["BUY", "SELL"]:
        sig["symbol"] = sym
        sig["exch"] = "NSE"
        order_resp = place_order_from_signal(ps_api, sig)
        return {"symbol": sym, "status": "order", "resp": order_resp}

    return {"symbol": sym, "status": "neutral"}


# =====================================================================
#  🔥 MAIN AUTO TRADER LOOP (CONTINUOUS)
# =====================================================================
def auto_trade_loop(ps_api, settings, symbols):
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
    # Load credentials from environment variables (Render)
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

    if not ps_api.is_logged_in():
        print("❌ Login failed. Check credentials.")
        exit(1)

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

    # Start hammer monitor thread
    import threading
    threading.Thread(
        target=monitor_open_positions,
        args=(ps_api, settings),
        daemon=True
    ).start()

    print("🧠 Hammer Exit Monitor started")

    # Start Auto Trader loop
    auto_trade_loop(ps_api, settings, symbols)

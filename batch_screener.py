#!/usr/bin/env python3
"""
batch_screener.py
Batch TPSeries screener: fetch watchlist symbols, compute TRM/MACD/PAC, produce BUY/SELL signals and place orders automatically.

Usage:
  python batch_screener.py --watchlists 1,2,3 --interval 5 --output signals.csv --place-orders
"""
import os
import time
import argparse
import json
from datetime import datetime
import pandas as pd

# Local modules
from prostocks_connector import ProStocksAPI
from dashboard_logic import load_credentials  # For session
import tkp_trm_chart as trm

# -----------------------
# Utility helpers
# -----------------------
def tz_normalize_df(df):
    if "datetime" not in df.columns:
        return pd.DataFrame()
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    if df["datetime"].dt.tz is None:
        df["datetime"] = df["datetime"].dt.tz_localize("Asia/Kolkata")
    else:
        df["datetime"] = df["datetime"].dt.tz_convert("Asia/Kolkata")
    df = df.dropna(subset=["datetime", "open", "high", "low", "close"])
    return df.reset_index(drop=True)

def suggested_qty_by_value(price, target_value_inr=1000):
    try:
        price = float(price)
    except Exception:
        return 0
    if price <= 0:
        return 0
    qty = int(target_value_inr // price)
    return max(1, qty)

# -----------------------
# Signal generation
# -----------------------
def generate_signal_for_df(df, settings):
    df = df.copy()
    df = trm.calc_tkp_trm(df, settings)
    df = trm.calc_macd(df, settings)
    df = trm.calc_pac(df, settings)
    df = trm.calc_atr_trails(df, settings)
    df = trm.calc_yhl(df)

    if df.empty:
        return None

    last = df.iloc[-1]
    last_price = float(last.get("close", 0))
    last_dt = last.get("datetime")

    tsi_sig = last.get("trm_signal", "Neutral")
    macd_hist = last.get("macd_hist", 0)
    pacC = last.get("pacC", None)
    trail1 = last.get("Trail1", None)

    reasons = []
    signal = "NEUTRAL"

    if tsi_sig == "Buy" and (macd_hist and macd_hist > 0) and (pacC is None or last_price > pacC):
        signal = "BUY"
        reasons.append("TSI=Buy")
        reasons.append("MACD hist > 0")
        if pacC is not None:
            reasons.append("Price > PAC mid")
    elif tsi_sig == "Sell" and (macd_hist and macd_hist < 0) and (pacC is None or last_price < pacC):
        signal = "SELL"
        reasons.append("TSI=Sell")
        reasons.append("MACD hist < 0")
        if pacC is not None:
            reasons.append("Price < PAC mid")
    else:
        signal = "NEUTRAL"
        reasons.append("No confluence")

    stop_loss = trail1 if trail1 is not None else None
    suggested_qty = suggested_qty_by_value(last_price, target_value_inr=1000)

    return {
        "signal": signal,
        "reason": " & ".join(reasons),
        "last_price": last_price,
        "last_dt": str(last_dt),
        "stop_loss": stop_loss,
        "suggested_qty": suggested_qty
    }

# -----------------------
# Place Order Helper (manual order format)
# -----------------------
def place_order_from_signal(ps_api, sig):
    """
    Converts signal to ProStocksAPI manual order format
    """
    signal = sig.get("signal")
    tsym = sig.get("symbol")  # tradingsymbol like SBIN-EQ
    exch = "NSE"              # default NSE
    qty = sig.get("suggested_qty", 1)
    last_price = sig.get("last_price", 0)

    if signal not in ["BUY", "SELL"]:
        return None

    bos = "B" if signal == "BUY" else "S"

    price_type = "MKT"
    price_val = None if price_type == "MKT" else last_price

    try:
        order = ps_api.place_order(
            buy_or_sell=bos,
            product_type="C",
            exchange=exch,
            tradingsymbol=tsym,
            quantity=qty,
            discloseqty=0,
            price_type=price_type,
            price=price_val,
            remarks=f"batch_{signal}"
        )
        print(f"✅ Order placed for {tsym}: {signal} x {qty}")
        return order
    except Exception as e:
        print(f"❌ Order failed for {tsym}: {e}")
        return None

# -----------------------
# Per-symbol processing
# -----------------------
def process_symbol_symbolic(ps_api, symbol_obj, interval, settings):
    tsym = symbol_obj.get("tsym")  # always human-readable symbol
    exch = symbol_obj.get("exch", "NSE")
    token = str(symbol_obj.get("token", ""))

    if not tsym:
        return {"symbol": f"{exch}|{token}", "status": "error", "emsg": "Missing tsym for PlaceOrder"}

    try:
        df = ps_api.fetch_full_tpseries(exch, token, interval)
    except Exception as e:
        return {"symbol": tsym, "status": "error", "emsg": str(e)}

    if isinstance(df, dict):
        return {"symbol": tsym, "status": "error", "emsg": json.dumps(df)}
    if df.empty:
        return {"symbol": tsym, "status": "no_data"}

    if "into" in df.columns and "open" not in df.columns:
        df = df.rename(columns={"into": "open", "inth": "high", "intl": "low", "intc": "close", "intv": "volume"})

    df = tz_normalize_df(df)
    if df.empty:
        return {"symbol": tsym, "status": "no_data_after_norm"}

    sig = generate_signal_for_df(df, settings)
    if sig is None:
        return {"symbol": tsym, "status": "no_data_after_indicators"}

    return {
        "symbol": tsym,
        "exch": exch,
        "token": token,
        "status": "ok",
        **sig
    }

# -----------------------
# Main runner
# -----------------------
def main(args, ps_api=None):
    if ps_api is None:
        creds = load_credentials()
        ps_api = ProStocksAPI(**creds)
        if not ps_api.is_logged_in():
            print("❌ Not logged in. Please login via dashboard first.")
            return
        print("Using new session from credentials")

    from tkp_trm_chart import load_trm_settings_from_file
    settings = load_trm_settings_from_file()

    # Fetch symbols
    all_symbols = []
    if args.all_watchlists:
        wls = ps_api.get_watchlists()
        if wls.get("stat") != "Ok":
            print("Failed to list watchlists:", wls)
            return
        watchlist_ids = sorted(wls["values"], key=int)
    else:
        watchlist_ids = [w.strip() for w in args.watchlists.split(",") if w.strip()]

    for wl in watchlist_ids:
        wl_data = ps_api.get_watchlist(wl)
        if wl_data.get("stat") != "Ok":
            print(f"Could not load watchlist {wl}: {wl_data.get('emsg')}")
            continue
        all_symbols.extend(wl_data.get("values", []))

    seen, unique_symbols = set(), []
    for s in all_symbols:
        key = f"{s.get('exch')}|{s.get('token')}"
        if key not in seen:
            seen.add(key)
            unique_symbols.append(s)
    all_symbols = unique_symbols

    print(f"Total symbols to process: {len(all_symbols)}")

    results = []
    calls_made, window_start = 0, time.time()

    for idx, sym in enumerate(all_symbols, 1):
        calls_made += 1
        elapsed = time.time() - window_start
        if calls_made > args.max_calls_per_min:
            to_wait = max(0, 60 - elapsed) + 0.5
            print(f"Rate limit reached. Sleeping {to_wait:.1f}s...")
            time.sleep(to_wait)
            window_start, calls_made = time.time(), 1

        print(f"[{idx}/{len(all_symbols)}] {sym.get('tsym')} ...")
        try:
            r = process_symbol_symbolic(ps_api, sym, args.interval, settings)
        except Exception as e:
            r = {"symbol": sym.get("tsym"), "status": "error", "emsg": str(e)}
        results.append(r)

        # Place order automatically if enabled
        if args.place_orders and r.get("signal") in ["BUY", "SELL"]:
            place_order_from_signal(ps_api, r)

        time.sleep(args.delay_between_calls)

    out_df = pd.DataFrame(results)
    out_file = args.output or f"signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out_df.to_csv(out_file, index=False)
    print("Saved results to", out_file)
    print("Summary:\n", out_df["signal"].value_counts(dropna=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch TPSeries Screener -> TRM+MACD+PAC signals")
    parser.add_argument("--watchlists", type=str, default="1")
    parser.add_argument("--all-watchlists", action="store_true")
    parser.add_argument("--interval", type=str, default="5")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--max-calls-per-min", type=int, default=15)
    parser.add_argument("--delay-between-calls", type=float, default=0.25)
    parser.add_argument("--place-orders", action="store_true", help="🚀 Place orders when BUY/SELL signal found")
    args = parser.parse_args()
    main(args)


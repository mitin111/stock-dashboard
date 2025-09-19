#!/usr/bin/env python3
"""
batch_screener.py
Batch TPSeries screener: fetch watchlist symbols, compute TRM/MACD/PAC, produce BUY/SELL signals.

Usage:
  python batch_screener.py --watchlists 1,2,3 --interval 5 --output signals.csv
"""
import os
import time
import argparse
import math
import json
from datetime import datetime, timezone
import pandas as pd

# Local modules (must exist in same folder / pythonpath)
from prostocks_connector import ProStocksAPI
import tkp_trm_chart as trm

# -----------------------
# Utility helpers
# -----------------------
def load_credentials_flexible():
    """
    Try to import dashboard_logic.load_credentials() else read from environment.
    Returns dict with keys accepted by ProStocksAPI constructor.
    """
    creds = {}
    try:
        from dashboard_logic import load_credentials
        creds = load_credentials()
        # map keys: dashboard_logic likely returns keys named uid,pwd,vc,api_key,imei,base_url,apkversion
        # normalize names for ProStocksAPI constructor
        return {
            "userid": creds.get("uid") or creds.get("userid"),
            "password_plain": creds.get("pwd") or creds.get("password_plain"),
            "vc": creds.get("vc"),
            "api_key": creds.get("api_key"),
            "imei": creds.get("imei"),
            "base_url": creds.get("base_url"),
            "apkversion": creds.get("apkversion", "1.0.0")
        }
    except Exception:
        # fallback to environment vars
        return {
            "userid": os.getenv("PROSTOCKS_USER_ID"),
            "password_plain": os.getenv("PROSTOCKS_PASSWORD"),
            "vc": os.getenv("PROSTOCKS_VENDOR_CODE"),
            "api_key": os.getenv("PROSTOCKS_API_KEY"),
            "imei": os.getenv("PROSTOCKS_MAC"),
            "base_url": os.getenv("PROSTOCKS_BASE_URL"),
            "apkversion": os.getenv("PROSTOCKS_APKVERSION", "1.0.0")
        }

def tz_normalize_df(df):
    """Ensure df['datetime'] exists and is tz-aware Asia/Kolkata, drop nulls."""
    if "datetime" not in df.columns:
        return pd.DataFrame()
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    if df["datetime"].dt.tz is None:
        df["datetime"] = df["datetime"].dt.tz_localize("Asia/Kolkata")
    else:
        df["datetime"] = df["datetime"].dt.tz_convert("Asia/Kolkata")
    df = df.dropna(subset=["datetime", "open", "high", "low", "close"])
    # keep column datetime (not index) as trm functions expect that
    df = df.reset_index(drop=True)
    return df

def suggested_qty_by_value(price, target_value_inr=1000):
    """Simple suggested qty: invest ~target_value_inr per symbol (min 1)."""
    try:
        price = float(price)
    except Exception:
        return 0
    if price <= 0:
        return 0
    qty = int(target_value_inr // price)
    return max(1, qty)

# -----------------------
# Signal generation logic
# -----------------------
def generate_signal_for_df(df, settings):
    """
    Run indicators from tkp_trm_chart and produce a signal dict for the last bar.
    Returns dict with keys: signal (BUY/SELL/NEUTRAL), reason, last_price, last_dt, stop_loss
    """
    # Apply indicators (these functions modify df in-place and return df)
    # Guard: work on a copy
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

    # Basic example rule:
    if tsi_sig == "Buy" and (macd_hist is not None and macd_hist > 0) and (pacC is None or last_price > pacC):
        signal = "BUY"
        reasons.append("TSI=Buy")
        reasons.append("MACD hist > 0")
        if pacC is not None:
            reasons.append("Price > PAC mid")
    elif tsi_sig == "Sell" and (macd_hist is not None and macd_hist < 0) and (pacC is None or last_price < pacC):
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
# Per-symbol processing
# -----------------------
def process_symbol_symbolic(ps_api, symbol_obj, interval, settings):
    """
    symbol_obj = dict with keys 'exch','token','tsym'
    Returns result dict.
    """
    exch = symbol_obj.get("exch")
    token = str(symbol_obj.get("token"))
    tsym = symbol_obj.get("tsym", f"{exch}|{token}")

    try:
        df = ps_api.fetch_full_tpseries(exch, token, interval)
    except Exception as e:
        return {"symbol": tsym, "status": "error", "emsg": str(e)}

    if isinstance(df, dict):
        # API returned error dict
        return {"symbol": tsym, "status": "error", "emsg": json.dumps(df)}

    if df.empty:
        return {"symbol": tsym, "status": "no_data"}

    # Normalize column names if API returned 'into', 'inth' etc.
    rename_map = {}
    if "into" in df.columns and "open" not in df.columns:
        rename_map.update({"into": "open", "inth": "high", "intl": "low", "intc": "close", "intv": "volume"})
    if rename_map:
        df = df.rename(columns=rename_map)

    df = tz_normalize_df(df)
    if df.empty:
        return {"symbol": tsym, "status": "no_data_after_norm"}

    # Generate signal
    sig = generate_signal_for_df(df, settings)
    if sig is None:
        return {"symbol": tsym, "status": "no_data_after_indicators"}

    result = {
        "symbol": tsym,
        "exch": exch,
        "token": token,
        "status": "ok",
        "last_dt": sig["last_dt"],
        "last_price": sig["last_price"],
        "signal": sig["signal"],
        "reason": sig["reason"],
        "stop_loss": sig["stop_loss"],
        "suggested_qty": sig["suggested_qty"]
    }
    return result

# -----------------------
# Main runner
# -----------------------
def main(args):
    creds = load_credentials_flexible()
    ps_api = ProStocksAPI(
        userid=creds.get("userid"),
        password_plain=creds.get("password_plain"),
        vc=creds.get("vc"),
        api_key=creds.get("api_key"),
        imei=creds.get("imei"),
        base_url=creds.get("base_url"),
        apkversion=creds.get("apkversion", "1.0.0")
    )

    # Login (interactive if needed)
    otp = args.otp
    if not otp:
        print("Sending OTP (QuickAuth) ...")
        resp = ps_api.send_otp()
        print("OTP trigger response:", resp)
        otp = input("Enter OTP from SMS/Email: ").strip()
    ok, msg_or_token = ps_api.login(otp)
    if not ok:
        print("Login failed:", msg_or_token)
        return
    print("Login success. Session token set.")

    # Load settings (from tkp_trm_chart.json or defaults)
    settings = trm.load_trm_settings() or {
        "long": 25, "short": 5, "signal": 14,
        "len_rsi": 5, "rsiBuyLevel": 50, "rsiSellLevel": 50,
        "buyColor": "#00FFFF", "sellColor": "#FF00FF", "neutralColor": "#808080",
        "pac_length": 34, "use_heikin_ashi": True,
        "atr_fast_period": 5, "atr_fast_mult": 0.5,
        "atr_slow_period": 10, "atr_slow_mult": 3.0,
        "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
        "show_info_panels": True
    }

    # Prepare symbol list from watchlists
    all_symbols = []
    if args.all_watchlists:
        wls = ps_api.get_watchlists()
        if wls.get("stat") != "Ok":
            print("Failed to list watchlists:", wls)
            return
        saved = sorted(wls["values"], key=int)
        watchlist_ids = saved
    else:
        watchlist_ids = [w.strip() for w in args.watchlists.split(",") if w.strip()]

    for wl in watchlist_ids:
        print(f"Fetching watchlist {wl} ...")
        wl_data = ps_api.get_watchlist(wl)
        if wl_data.get("stat") != "Ok":
            print(f"  Could not load watchlist {wl}: {wl_data.get('emsg')}")
            continue
        values = wl_data.get("values", [])
        for s in values:
            # each s is dict like {'exch':'NSE','token':22,'tsym':'TCS'}
            all_symbols.append(s)

    # dedupe by exch|token
    seen = set()
    unique_symbols = []
    for s in all_symbols:
        key = f"{s.get('exch')}|{s.get('token')}"
        if key not in seen:
            seen.add(key)
            unique_symbols.append(s)
    all_symbols = unique_symbols

    print(f"Total symbols to process: {len(all_symbols)}")

    results = []
    calls_made = 0
    window_start = time.time()
    max_calls_per_min = args.max_calls_per_min

    for idx, sym in enumerate(all_symbols, 1):
        # rate limit
        calls_made += 1
        elapsed = time.time() - window_start
        if calls_made > max_calls_per_min:
            # wait until 60 sec window passes
            to_wait = max(0, 60 - elapsed) + 0.5
            print(f"Rate limit reached. Sleeping for {to_wait:.1f}s...")
            time.sleep(to_wait)
            window_start = time.time()
            calls_made = 1

        print(f"[{idx}/{len(all_symbols)}] Processing {sym.get('tsym')} ({sym.get('exch')}|{sym.get('token')}) ...")
        try:
            r = process_symbol_symbolic(ps_api, sym, args.interval, settings)
        except Exception as e:
            r = {"symbol": sym.get("tsym"), "status": "error", "emsg": str(e)}
        results.append(r)
        # small pause to avoid burst
        time.sleep(args.delay_between_calls)

    # Save results
    out_df = pd.DataFrame(results)
    out_file = args.output or f"signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out_df.to_csv(out_file, index=False)
    print("Saved results to", out_file)
    # quick summary
    print("Summary:")
    print(out_df["signal"].value_counts(dropna=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch TPSeries Screener -> TRM+MACD+PAC signals")
    parser.add_argument("--watchlists", type=str, default="1", help="Comma separated watchlist ids (e.g. 1,2,3)")
    parser.add_argument("--all-watchlists", dest="all_watchlists", action="store_true", help="Process all saved watchlists")
    parser.add_argument("--interval", type=str, default="5", help="TPSeries interval minutes (default 5)")
    parser.add_argument("--otp", type=str, default=None, help="OTP if you already have it")
    parser.add_argument("--output", type=str, default=None, help="Output CSV file path")
    parser.add_argument("--max-calls-per-min", type=int, default=15, dest="max_calls_per_min", help="Rate-limit calls per minute")
    parser.add_argument("--delay-between-calls", type=float, default=0.25, dest="delay_between_calls", help="Small delay between calls (s)")
    args = parser.parse_args()
    main(args)

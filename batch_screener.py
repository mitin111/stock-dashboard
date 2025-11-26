#!/usr/bin/env python3
"""
batch_screener_debug.py
Batch TPSeries screener with automatic order placement (BUY/SELL)
Debug-friendly: logs all errors, missing data, session issues, signals, orders.

Usage:
  python batch_screener_debug.py --watchlists 1,2,3 --interval 5 --output signals.csv --place-orders
"""
import os
import pandas as pd
import pytz

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRM_FILE = os.path.join(BASE_DIR, "trm_settings.json")

print("🔍 Using TRM file:", TRM_FILE)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_PATH = os.path.join(BASE_DIR, "live_candles")


def load_live_5min(sym):

    sym = str(sym).upper().strip()

    # Try both: with and without -EQ
    filename_variants = [sym, sym.replace("-EQ", "")]

    for f in filename_variants:
        fn = os.path.join(LIVE_PATH, f"{f}.json")
        print("🔍 Looking for:", fn)

        if os.path.exists(fn):
            try:
                df = pd.read_json(fn)

                if df.empty:
                    print(f"⚠️ Empty candle file: {f}")
                    return df

                df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")

                if df["datetime"].dt.tz is None:
                    df["datetime"] = df["datetime"].dt.tz_localize("Asia/Kolkata")
                else:
                    df["datetime"] = df["datetime"].dt.tz_convert("Asia/Kolkata")

                df["bucket"] = df["datetime"].dt.floor("5min")

                df = df.groupby("bucket").agg(
                    open=("open", "first"),
                    high=("high", "max"),
                    low=("low", "min"),
                    close=("close", "last"),
                    volume=("volume", "sum")
                ).reset_index().rename(columns={"bucket": "datetime"})

                return df.tail(200)

            except Exception as e:
                print(f"⚠️ load_live_5min error {f}: {e}")
                return pd.DataFrame()

    # If both not found
    print(f"❌ Tick data missing for {sym} (tried both)")
    return pd.DataFrame()

import os
import time
import argparse
import json
from datetime import datetime
import pandas as pd
import numpy as np

from prostocks_connector import ProStocksAPI
from dashboard_logic import place_order_from_signal, load_credentials
import tkp_trm_chart as trm
import threading

# -----------------------------
# ✅ Trade-cycle tracker (1 BUY + 1 SELL per day, non-consecutive)
# -----------------------------
import datetime
import pytz

def check_trade_cycle_status(ps_api, symbol):
    import datetime, pytz
    try:
        resp = ps_api.trade_book()
        if not resp:
            return {"buy_cycle_done": False, "sell_cycle_done": False, "full_lock": False, "last_side": "NONE"}

        all_trades = resp if isinstance(resp, list) else resp.get("data", [])
        if not all_trades:
            return {"buy_cycle_done": False, "sell_cycle_done": False, "full_lock": False, "last_side": "NONE"}

        today = datetime.datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%d-%m-%Y")

        trades = [
            t for t in all_trades
            if t.get("tsym") == symbol and (t.get("norentm") or "").split(" ")[-1] == today
        ]

        if not trades:
            return {"buy_cycle_done": False, "sell_cycle_done": False, "full_lock": False, "last_side": "NONE"}

        trades.sort(key=lambda x: x.get("norentm") or "")
        sides = [t.get("trantype") for t in trades if t.get("trantype") in ["B","S"]]

        if not sides:
            return {"buy_cycle_done": False, "sell_cycle_done": False, "full_lock": False, "last_side": "NONE"}

        # -----------------------------
        # ✅ Detect non-consecutive BUY→SELL and SELL→BUY
        # -----------------------------
        buy_seen = False
        buy_sell_done = False
        sell_seen = False
        sell_buy_done = False

        for side in sides:
            if side == "B":
                buy_seen = True
                if sell_seen:
                    sell_buy_done = True
            elif side == "S":
                sell_seen = True
                if buy_seen:
                    buy_sell_done = True

        last_side = sides[-1]

        # ✅ Final cycle flags
        buy_cycle_done = buy_sell_done
        sell_cycle_done = sell_buy_done
        full_lock = sell_buy_done  # SELL→BUY completion locks both

        # If no full cycle yet, prevent duplicate same-side
        if not buy_sell_done and not sell_buy_done:
            if last_side == "B":
                buy_cycle_done = True  # block BUY until SELL happens
            elif last_side == "S":
                sell_cycle_done = True  # block SELL until BUY happens

        return {
            "buy_cycle_done": buy_cycle_done,
            "sell_cycle_done": sell_cycle_done,
            "full_lock": full_lock,
            "last_side": last_side
        }

    except Exception as e:
        print(f"⚠️ Error in check_trade_cycle_status({symbol}): {e}")
        return {"buy_cycle_done": False, "sell_cycle_done": False, "full_lock": False, "last_side": "NONE"}


# Helper: compute safe SL and TP
def compute_safe_sl_tp(last_price, pac_val, side,
                       rr=2.0, max_sl_pct=0.03, min_sl_pct=0.001, atr=None):
    try:
        last_price = float(last_price)
    except Exception:
        return None, None

    pac = None
    try:
        if pac_val is not None and str(pac_val).strip() != "":
            pac = float(pac_val)
    except Exception:
        pac = None

    def cap_dist(dist):
        max_dist = last_price * max_sl_pct
        min_dist = last_price * min_sl_pct
        if dist > max_dist:
            return max_dist
        if dist < min_dist:
            return min_dist
        return dist

    stop = None

    if side == "BUY":
        if pac is not None and pac < last_price:
            dist = last_price - pac
            if (dist / last_price) > max_sl_pct:
                dist = cap_dist(dist)
                stop = last_price - dist
            elif (dist / last_price) < min_sl_pct:
                dist = cap_dist(dist)
                stop = last_price - dist
            else:
                stop = pac
        else:
            if atr:
                try:
                    dist = float(atr)
                except Exception:
                    dist = last_price * max_sl_pct
            else:
                dist = last_price * max_sl_pct
            dist = cap_dist(dist)
            stop = last_price - dist

    else:  # SELL
        if pac is not None and pac > last_price:
            dist = pac - last_price
            if (dist / last_price) > max_sl_pct:
                dist = cap_dist(dist)
                stop = last_price + dist
            elif (dist / last_price) < min_sl_pct:
                dist = cap_dist(dist)
                stop = last_price + dist
            else:
                stop = pac
        else:
            if atr:
                try:
                    dist = float(atr)
                except Exception:
                    dist = last_price * max_sl_pct
            else:
                dist = last_price * max_sl_pct
            dist = cap_dist(dist)
            stop = last_price + dist

    if side == "BUY" and stop >= last_price:
        stop = last_price - (last_price * max_sl_pct)
    if side == "SELL" and stop <= last_price:
        stop = last_price + (last_price * max_sl_pct)

    if side == "BUY":
        dist = last_price - stop
        target = last_price + (dist * rr)
    else:
        dist = stop - last_price
        target = last_price - (dist * rr)

    stop = round(stop, 2)
    target = round(target, 2)
    return stop, target

# -----------------------
# Helpers
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
# API response helpers
# -----------------------
def resp_to_status_and_list(resp):
    if isinstance(resp, dict):
        stat = resp.get("stat")
        data = resp.get("data")
        if data is None:
            # If dict looks like an item (has order-like keys), return it as single-item list
            # Heuristic: presence of 'norenordno' or 'tsym' or 'trantype'
            if any(k in resp for k in ("norenordno", "tsym", "trantype", "trading_symbol")):
                return stat, [resp]
            return stat, []
        if isinstance(data, list):
            return stat, data
        if isinstance(data, dict):
            return stat, [data]
        return stat, []
    elif isinstance(resp, list):
        return None, resp
    else:
        return None, []

# ----------------------- 
# Signal generation with debug
# -----------------------
def generate_signal_for_df(df, settings):
    try:
        df = df.copy()
        df = trm.calc_tkp_trm(df, settings)
        df = trm.calc_macd(df, settings)
        df = trm.calc_pac(df, settings)
        df = trm.calc_atr_trails(df, settings)
        df = trm.calc_yhl(df)
        df = trm.calc_gap_move_flag(df)
        df = trm.calc_intraday_volatility_flag(df)  # ✅ add this line if defined in tkp_trm_chart.py
        df = trm.calc_day_move_flag(df)  # ✅ new day move indicator (adds day_move_pct + flag)
    except Exception as e:
        print(f"❌ Error calculating indicators for {df.iloc[-1].name if not df.empty else 'unknown'}: {e}")
        print("🔹 Last few rows of dataframe causing error:\n", df.tail())
        return None

    if df.empty:
        print("⚠️ Dataframe empty after indicators")
        return None

    last = df.iloc[-1]
    last_price = float(last.get("close", 0))
    last_dt = last.get("datetime")

    tsi_sig = last.get("trm_signal", "Neutral")
    macd_hist = float(last.get("macd_hist", 0) or 0)
    pacC = last.get("pacC", None)
    pac_lower = last.get("pacL", None)
    pac_upper = last.get("pacU", None)

    latest_day = df["datetime"].iloc[-1].date()
    day_data = df[df["datetime"].dt.date == latest_day].copy()
    day_high = day_data["high"].max() if not day_data.empty else last_price
    day_low = day_data["low"].min() if not day_data.empty else last_price
    volatility = ((day_high - day_low) / day_low) * 100 if day_low > 0 else 0

    reasons, signal = [], None

    # ============================================================
    # 🔎 Intraday volatility filter (same-day high-range candles)
    # ============================================================
    try:
        skip_due_to_intraday_vol = False
        intraday_df = day_data.copy(deep=True)
        intraday_df["range_pct"] = ((intraday_df["high"] - intraday_df["low"]) / intraday_df["low"]) * 100

        # --- (1) Any single candle > 1.3% range ---
        if (intraday_df["range_pct"] >= 1.3).any():
            skip_due_to_intraday_vol = True
            reasons.append("⚠️ Intraday candle >1.3% range — skipping trade")

        # --- (2) Two consecutive candles combined > 2% move ---
        if len(intraday_df) >= 2:
            intraday_df["close_change_pct"] = intraday_df["close"].pct_change() * 100
            intraday_df["two_candle_move"] = intraday_df["close_change_pct"].rolling(2).sum().abs()
            if (intraday_df["two_candle_move"] >= 2).any():
                skip_due_to_intraday_vol = True
                reasons.append("⚠️ Two consecutive candles ≥2% combined move — skipping trade")

        if skip_due_to_intraday_vol:
            signal = None
    except Exception as e:
        reasons.append(f"⚠️ Intraday volatility check failed: {e}")

    # ============================================================
    # 🔹 Core signal logic (TSI + MACD + PAC)
    # ============================================================
    if signal is None:  # only compute if not skipped
        if tsi_sig == "Buy" and macd_hist > 0 and (pacC is None or last_price > pacC):
            signal = "BUY"
            reasons.append("TSI=Buy & MACD hist >0")
            if pacC is not None:
                reasons.append("Price > PAC mid")
        elif tsi_sig == "Sell" and macd_hist < 0 and (pacC is None or last_price < pacC):
            signal = "SELL"
            reasons.append("TSI=Sell & MACD hist <0")
            if pacC is not None:
                reasons.append("Price < PAC mid")
        else:
            if tsi_sig == "Neutral" and macd_hist != 0:
                reasons.append(f"Weak confluence: TSI Neutral, MACD {'pos' if macd_hist>0 else 'neg'}")
            else:
                reasons.append("No confluence")

    # ============================================================
    # 🔹 Yesterday High/Low Filter
    # ============================================================
    y_high = last.get("high_yest")
    y_low = last.get("low_yest")

    if signal == "BUY" and y_high is not None and last_price <= y_high:
        reasons.append(f"Price {last_price:.2f} ≤ Yesterday High {y_high:.2f}, skipping BUY")
        signal = None

    if signal == "SELL" and y_low is not None and last_price >= y_low:
        reasons.append(f"Price {last_price:.2f} ≥ Yesterday Low {y_low:.2f}, skipping SELL")
        signal = None

    # ============================================================
    # 🔹 Time-based volatility safeguard
    # ============================================================
    last_candle_time = pd.to_datetime(df["datetime"].iloc[-1]).time()
    vol_threshold = 1.0
    t = datetime.datetime.strptime

    if t("09:15", "%H:%M").time() <= last_candle_time < t("09:20", "%H:%M").time():
        vol_threshold = 1.60
    elif t("09:20", "%H:%M").time() <= last_candle_time < t("10:00", "%H:%M").time():
        vol_threshold = 1.80
    elif t("10:00", "%H:%M").time() <= last_candle_time < t("11:00", "%H:%M").time():
        vol_threshold = 2.00
    elif t("11:00", "%H:%M").time() <= last_candle_time < t("12:00", "%H:%M").time():
        vol_threshold = 2.20
    elif t("12:00", "%H:%M").time() <= last_candle_time < t("13:00", "%H:%M").time():
        vol_threshold = 2.40
    elif t("13:00", "%H:%M").time() <= last_candle_time < t("14:00", "%H:%M").time():
        vol_threshold = 2.80
    elif t("14:00", "%H:%M").time() <= last_candle_time <= t("14:45", "%H:%M").time():
        vol_threshold = 2.80
    elif t("14:45", "%H:%M").time() <= last_candle_time <= t("15:25", "%H:%M").time():
        vol_threshold = 2.60

    if volatility < vol_threshold:
        signal = "NEUTRAL"
        reasons.append(f"Volatility {volatility:.2f}% < {vol_threshold}, skipping trade")

    # ============================================================
    # 🔹 Day Move Filter (from indicator)
    # ============================================================
    day_move_pct = float(last.get("day_move_pct", 0) or 0)

    # ✅ NaN protection
    if pd.isna(day_move_pct):
        day_move_pct = 0.0

    # ✅ Boolean cast to avoid "string True"/"NaN" issue
    if bool(last.get("skip_due_to_day_move", False)):
        signal = None
        reasons.append(f"⚠️ Price moved {day_move_pct:.2f}% from open (>1.5%), skipping trade")

    # ============================================================
    # 🔹 Gap Move Filter (from indicator)
    # ============================================================
    gap_pct = float(last.get("gap_pct", 0) or 0)

    # ✅ NaN protection
    if pd.isna(gap_pct):
        gap_pct = 0.0

    if bool(last.get("skip_due_to_gap", False)):
        signal = None
        reasons.append(f"⚠️ Gap {gap_pct:.2f}% from yesterday close (>1.0%), skipping trade")

    # ============================================================
    # 🔹 Stop-loss setup
    # ============================================================
    stop_loss = None
    if signal == "BUY" and pac_lower is not None:
        stop_loss = pac_lower
        reasons.append(f"SL = PAC Lower {pac_lower:.2f}")
    elif signal == "SELL" and pac_upper is not None:
        stop_loss = pac_upper
        reasons.append(f"SL = PAC Upper {pac_upper:.2f}")

    suggested_qty = trm.suggested_qty_by_mapping(last_price)

    if signal not in ["BUY", "SELL"]:
        signal = None

    return {
        "signal": signal,
        "reason": " & ".join(reasons),
        "last_price": last_price,
        "last_dt": str(last_dt),
        "stop_loss": stop_loss,
        "suggested_qty": suggested_qty,
        "volatility": round(volatility, 2),
        "pac_lower": pac_lower,
        "pac_upper": pac_upper
    }


# ================================================================
# ✅ Dynamic Target/Trail + Auto Order Placement (ProStocks API)
# ================================================================
# ✅ Updated: dynamic target/trail + stop-loss min/max per bucket
import datetime, pytz
from typing import Tuple, Optional

def get_dynamic_target_trail(volatility: float) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Return (target_pct, trail_pct, min_sl_pct, max_sl_pct) based on current time and volatility.
    volatility: in percent (e.g. 2.45)
    """
    volatility = round(float(volatility), 2)
    now = datetime.datetime.now(pytz.timezone("Asia/Kolkata")).time()

    def in_range(start, end):
        return start <= now <= end

    # Each row: (lo, hi, target_pct, trail_pct, min_sl_pct, max_sl_pct)
    if in_range(datetime.time(9, 20), datetime.time(9, 30)):
        table = [
            (1.61, 1.8, 1.0, 0.3, 0.3, 0.5),
            (1.81, 2.0, 1.0, 0.4, 0.3, 0.5),
            (2.01, 2.2, 1.3, 0.7, 0.3, 1.0),
            (2.21, 2.4, 2.0, 0.9, 0.3, 1.1),
            (2.41, 2.6, 2.3, 1.0, 0.3, 1.1),
            (2.61, 2.8, 2.5, 1.0, 0.3, 1.1),
            (2.81, 3.0, 3.0, 1.0, 0.3, 1.1),
            (3.01, 999, 3.0, 1.0, 0.3, 1.1),
        ]

    elif in_range(datetime.time(9, 30), datetime.time(10, 0)):
        table = [
            (1.81, 2.0, 1.3, 0.4, 0.3, 0.7),
            (2.01, 2.2, 1.5, 0.5, 0.3, 0.9),
            (2.21, 2.4, 1.7, 0.6, 0.3, 1.0),
            (2.41, 2.6, 2.0, 0.7, 0.3, 1.1),
            (2.61, 2.8, 2.2, 0.8, 0.3, 1.1),
            (2.81, 3.0, 2.5, 0.9, 0.3, 1.1),
            (3.01, 3.2, 3.0, 1.0, 0.3, 1.1),
            (3.21, 999, 3.5, 1.1, 0.3, 1.1),
        ]

    elif in_range(datetime.time(10, 0), datetime.time(11, 0)):
        table = [
            (2.01, 2.2, 1.0, 0.3, 0.3, 0.7),
            (2.21, 2.4, 1.2, 0.4, 0.3, 0.8),
            (2.41, 2.6, 1.5, 0.5, 0.3, 0.9),
            (2.61, 2.8, 1.7, 0.7, 0.3, 1.0),
            (2.81, 3.0, 2.0, 0.8, 0.3, 1.1),
            (3.01, 3.2, 2.2, 0.9, 0.3, 1.1),
            (3.21, 999, 2.5, 1.0, 0.3, 1.1),
        ]

    elif in_range(datetime.time(11, 0), datetime.time(12, 0)):
        table = [
            (2.21, 2.4, 0.75, 0.3, 0.3, 0.5),
            (2.41, 2.6, 1.0, 0.4, 0.3, 0.6),
            (2.61, 2.8, 1.2, 0.5, 0.3, 0.7),
            (2.81, 3.0, 1.5, 0.6, 0.3, 0.7),
            (3.01, 999, 1.7, 0.7, 0.3, 0.8),
        ]

    elif in_range(datetime.time(12, 0), datetime.time(13, 0)):
        table = [
            (2.41, 2.6, 0.75, 0.3, 0.3, 0.5),
            (2.61, 2.8, 0.9, 0.3, 0.3, 0.6),
            (2.81, 3.0, 1.0, 0.3, 0.3, 0.7),
            (3.01, 999, 1.3, 0.3, 0.3, 0.7),
        ]

    elif in_range(datetime.time(13, 0), datetime.time(14, 0)):
        table = [
            (2.81, 3.0, 0.75, 0.3, 0.1, 0.5),
            (3.01, 999, 1.0, 0.3, 0.1, 0.5),
        ]

    elif in_range(datetime.time(14, 0), datetime.time(14, 45)):
        table = [
            (2.81, 3.0, 0.75, 0.3, 0.1, 0.5),
            (3.01, 999, 0.75, 0.3, 0.1, 0.5),
        ]

    else:
        # after 14:45 / market close testing table
        table = [
            (2.81, 3.0, 0.75, 0.3, 0.1, 0.3),
            (3.01, 999, 1.0, 0.3, 0.1, 0.3),
        ]

    for lo, hi, tgt, trail, min_sl_pct, max_sl_pct in table:
        if lo <= volatility <= hi:
            return (tgt, trail, min_sl_pct, max_sl_pct)

    return (None, None, None, None)


# ✅ Updated place_order_from_signal to use returned min/max SL %
def place_order_from_signal(ps_api, sig):
    symbol = sig.get("symbol")
    signal_type = (sig.get("signal") or "").upper()

    if signal_type not in ["BUY", "SELL"]:
        print(f"⚠️ Skipping order for {symbol}: invalid/neutral signal")
        return [{"stat": "Skipped", "emsg": "No valid signal"}]

    cycle = check_trade_cycle_status(ps_api, symbol)
    if signal_type == "BUY" and cycle.get("buy_cycle_done"):
        return [{"stat": "Skipped", "emsg": "BUY cycle completed"}]
    if signal_type == "SELL" and cycle.get("sell_cycle_done"):
        return [{"stat": "Skipped", "emsg": "SELL cycle completed"}]

    lower_band = sig.get("pac_lower")
    upper_band = sig.get("pac_upper")
    ltp = sig.get("ltp")
    exch = sig.get("exch", "NSE")

    from datetime import datetime, time
    now = datetime.now().time()
    market_open, market_close = time(9, 15), time(15, 30)

    if ltp is None:
        try:
            quote_resp = ps_api.get_quotes(symbol, exch)
            if quote_resp and quote_resp.get("stat") == "Ok" and quote_resp.get("lp"):
                ltp = float(quote_resp["lp"])
                sig["ltp"] = ltp
                print(f"📈 {symbol}: Live LTP fetched → {ltp}")
            else:
                ltp = float(sig.get("last_price") or 0)
                if ltp > 0:
                    print(f"🕒 {symbol}: Using fallback LTP → {ltp}")
                else:
                    if not (market_open <= now <= market_close):
                        print(f"⏳ {symbol}: Market closed ({now.strftime('%H:%M:%S')}) — using no trade mode")
                        return [{"stat": "Skipped", "emsg": "Market closed"}]
                    print(f"⚠️ {symbol}: LTP fetch failed — skipping order")
                    return [{"stat": "Skipped", "emsg": "LTP fetch failed"}]
        except Exception as e:
            print(f"⚠️ {symbol}: Exception fetching LTP → {e}")
            ltp = float(sig.get("last_price") or 0)
            if ltp > 0:
                print(f"ℹ️ {symbol}: Using last_price fallback after exception → {ltp}")
            else:
                return [{"stat": "Skipped", "emsg": f"LTP fetch exception: {e}"}]

    if lower_band is None or upper_band is None:
        print(f"⚠️ {symbol}: Missing PAC band data — skipping order")
        return [{"stat": "Skipped", "emsg": "Missing PAC band"}]

    if signal_type == "BUY" and ltp > lower_band * 1.02:
        return [{"stat": "Skipped", "emsg": "BUY >2% above lower band"}]
    if signal_type == "SELL" and ltp < upper_band * 0.98:
        return [{"stat": "Skipped", "emsg": "SELL >2% below upper band"}]

    vol = float(sig.get("volatility", 0))
    target_pct, trail_pct, min_sl_pct_table, max_sl_pct_table = get_dynamic_target_trail(vol)
    if target_pct is None:
        print(f"🚫 Skipping {symbol}: no match for vol {vol:.2f}% & current time")
        return [{"stat": "Skipped", "emsg": "No dynamic match"}]

    print(f"🕒 {symbol}: Vol={vol:.2f}% | Target={target_pct}% | Trail={trail_pct}% | SL% range=({min_sl_pct_table},{max_sl_pct_table})")

    pac_price = lower_band if signal_type == "BUY" else upper_band
    last_price = float(sig.get("last_price", ltp))
    pac_gap = abs(last_price - pac_price)

    min_sl_rs = last_price * (min_sl_pct_table / 100.0)
    max_sl_rs = last_price * (max_sl_pct_table / 100.0)

    # ensure sl_gap at least pac_gap but bounded between min_sl_rs and max_sl_rs
    sl_gap = max(pac_gap, min_sl_rs)
    sl_gap = min(sl_gap, max_sl_rs)

    # TP gap calculation based on target_pct (ensure at least min_sl_rs)
    tp_gap = max(last_price * (target_pct / 100.0), min_sl_rs)

    tick = 0.01 if ltp < 200 else 0.05
    blprc = round(sl_gap / tick) * tick
    bpprc = round(tp_gap / tick) * tick
    trail_rs = round(last_price * (trail_pct / 100.0), 2)

    try:
        raw_resp = ps_api.place_order(
            buy_or_sell="B" if signal_type == "BUY" else "S",
            product_type="B",
            exchange=exch,
            tradingsymbol=symbol,
            quantity=sig.get("suggested_qty", 1),
            discloseqty=0,
            price_type="MKT",
            price=0.0,
            trigger_price=0,
            book_profit=bpprc,
            book_loss=blprc,
            trail_price=trail_rs,
            remarks=f"Auto BO | Vol={vol:.2f}% | Tgt={target_pct}% | Trail={trail_pct}% | SLrange={min_sl_pct_table}-{max_sl_pct_table}"
        )

        if isinstance(raw_resp, dict):
            resp_list = [raw_resp]
        elif isinstance(raw_resp, list):
            resp_list = raw_resp
        else:
            resp_list = [{"stat": "Error", "emsg": str(raw_resp)}]

        ps_api._order_book = ps_api.order_book()
        ps_api._trade_book = ps_api.trade_book()

        for item in resp_list:
            if item.get("stat") == "Ok":
                print(f"✅ BO placed {symbol} | {signal_type} | SL={blprc} | TP={bpprc} | Trail={trail_rs}")
            else:
                print(f"❌ BO failed {symbol}: {item.get('rejreason') or item.get('emsg')}")
        return resp_list

    except Exception as e:
        print(f"❌ Exception placing BO for {symbol}: {e}")
        return [{"stat": "Exception", "emsg": str(e)}]


# ================================================================
# ✅ Periodic Order Monitor — Detect Hammer Reversal and Exit Trade
# ================================================================
# ================================================================
# ✅ Final Safe Version — Hammer Reversal Monitor (auto-exit)
# ================================================================
import time, sys
import pandas as pd
from datetime import datetime
import pytz

# Put this OUTSIDE the function (top of file)
active_orders = None


def monitor_open_positions(ps_api, settings):
    global active_orders      # <-- MUST BE FIRST LINE

    """
    Every 5 sec: check open orders, fetch chart, detect hammer reversal, exit trade if confirmed.
    """

    def safe_df(data):
        try:
            if isinstance(data, list):
                return pd.DataFrame(data)
            elif isinstance(data, dict):
                return pd.DataFrame([data])
            else:
                return pd.DataFrame()
        except Exception as e:
            print(f"⚠️ safe_df error: {e}")
            return pd.DataFrame()

    def fetch_chart_for_symbol(symbol, interval="5m", lookback=20):
        try:
            exch = "NSE"
            token = None
            try:
                token = ps_api.get_token(symbol)
            except Exception:
                if "|" in str(symbol):
                    token = symbol.split("|")[-1]

            df = ps_api.fetch_full_tpseries(exch, token, interval)
            df = safe_df(df)
            if df.empty:
                return pd.DataFrame()

            df = df.tail(lookback)
            for c in ["open", "high", "low", "close"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            df.dropna(subset=["open", "high", "low", "close"], inplace=True)

            return df

        except Exception as e:
            print(f"⚠️ Error fetching chart for {symbol}: {e}")
            return pd.DataFrame()

    def detect_hammer_patterns(df):
        if df.empty or len(df) < 3:
            return df

        df = df.copy()
        body = (df["close"] - df["open"]).abs()
        upper = df["high"] - df[["close", "open"]].max(axis=1)
        lower = df[["close", "open"]].min(axis=1) - df["low"]

        df["is_hammer"] = (lower > 2 * body) & (upper < body)
        df["is_inv_hammer"] = (upper > 2 * body) & (lower < body)
        return df

    def check_hammer_reversal(df, side):
        if len(df) < 3:
            return False

        last3 = df.tail(3).reset_index(drop=True)

        if side == "B":
            return (
                bool(last3.iloc[-3].get("is_hammer", False))
                and last3.iloc[-1]["close"] < last3.iloc[-3]["low"]
            )

        if side == "S":
            return (
                bool(last3.iloc[-3].get("is_inv_hammer", False))
                and last3.iloc[-1]["close"] > last3.iloc[-3]["high"]
            )

        return False

    def exit_trade(ps_api, symbol, side):
        try:
            order_book = ps_api.order_book()
            df = safe_df(order_book)
            if df.empty:
                print(f"⚠️ Empty order_book while exiting {symbol}")
                return

            if "tradingsymbol" not in df.columns:
                df["tradingsymbol"] = df.get("tsym") or df.get("trading_symbol")
            if "status" not in df.columns:
                df["status"] = df.get("Status")

            df["status_up"] = df["status"].astype(str).str.upper()

            df_active = df[
                (df["tradingsymbol"] == symbol)
                & (df["status_up"].isin(["OPEN", "TRIGGER_PENDING", "PENDING"]))
            ]
            if df_active.empty:
                print(f"⚠️ No open BO found for {symbol}")
                return

            ord_no = df_active.iloc[0].get("norenordno") or df_active.iloc[0].get("snonum")
            if not ord_no:
                print(f"⚠️ Missing norenordno for {symbol}")
                return

            payload = {
                "jKey": getattr(ps_api, "jKey", None),
                "uid": getattr(ps_api, "user_id", None),
                "prd": "B",
                "norenordno": ord_no,
            }
            print(f"📢 Attempting exit for {symbol} ({side}) | payload={payload}")
            resp = ps_api.post("/NorenWClientTP/ExitSNOOrder", payload)
            print(f"📨 ExitSNOOrder resp: {resp}")

        except Exception as e:
            print(f"❌ Exit trade exception for {symbol}: {e}")

    # === Monitor Loop ===
    print("🚀 Starting order monitor loop (5-sec interval)...")

    while True:
        try:
            order_book = ps_api.order_book()
            df_orders = safe_df(order_book)

            if df_orders.empty:
                active_orders = pd.DataFrame()
                print("ℹ️ No active/open orders to monitor yet.")
                time.sleep(5)
                continue

            if "tradingsymbol" not in df_orders.columns:
                if "tsym" in df_orders.columns:
                    df_orders["tradingsymbol"] = df_orders["tsym"]
                elif "trading_symbol" in df_orders.columns:
                    df_orders["tradingsymbol"] = df_orders["trading_symbol"]
                else:
                    df_orders["tradingsymbol"] = None

            if "status" not in df_orders.columns:
                df_orders["status"] = df_orders.get("Status")

            df_orders["status_up"] = df_orders["status"].astype(str).str.upper()

            df_orders = df_orders[df_orders["status_up"].isin(["OPEN", "TRIGGER_PENDING", "EXECUTED"])]

            active_orders = df_orders

            print(f"ℹ️ Active Orders: {len(active_orders)} being monitored...")

            for _, order in active_orders.iterrows():
                symbol = order.get("tradingsymbol") or order.get("tsym")
                side_raw = order.get("buy_or_sell") or order.get("trantype")
                side = str(side_raw).strip().upper()
                side = "B" if side in ["B", "BUY"] else "S"

                df_chart = fetch_chart_for_symbol(symbol)
                if df_chart.empty:
                    continue

                df_chart = detect_hammer_patterns(df_chart)

                if check_hammer_reversal(df_chart, side):
                    print(f"⚠️ Hammer reversal confirmed on {symbol}! Exiting...")
                    exit_trade(ps_api, symbol, side)
                    time.sleep(2)

        except Exception as e:
            print(f"⚠️ monitor_open_positions error: {e}")
            time.sleep(5)


# -----------------------
# Per-symbol processing
# -----------------------
def process_symbol(ps_api, symbol_obj, interval, settings):
    sym = symbol_obj.get("tsym")
    exch = symbol_obj.get("exch", "NSE")

    result = {"symbol": sym, "exch": exch, "status": "unknown"}

    # ✅ ONLY use tick_engine data (single source of truth)
    df = load_live_5min(sym)

    if df is None or df.empty:
        result.update({
            "status": "no_live_data",
            "emsg": "Tick data missing. Run tick_engine_worker.py"
        })
        return result

    if len(df) < 10:
        result.update({
            "status": "not_enough_candles",
            "emsg": f"Only {len(df)} candles found"
        })
        return result

    # Normalize time & clean
    df = tz_normalize_df(df)

    if df.empty:
        result.update({"status": "invalid_live_data"})
        return result

    # ✅ Indicators + signal (full strategy)
    sig = generate_signal_for_df(df, settings)

    if sig is None:
        result.update({"status": "no_signal"})
        return result

    result.update(sig)
    result.update({"status": "ok"})
    return result

# ============================================================
#  🔥 INSERTED: FAST HTML ORDER ENTRY STRATEGY BLOCK
# ============================================================
def run_strategy_request(ps_api, symbol, qty, side):
    """
    HTML order panel request → full strategy logic → filtered order
    """
    from tkp_trm_chart import (
        calc_tkp_trm, calc_pac, calc_macd, calc_atr_trails,
        get_trm_settings_safe,
        calc_gap_move_flag, calc_intraday_volatility_flag, calc_day_move_flag
    )
    import pandas as pd

    exch = "NSE"
    token = ps_api.search_scrip(symbol).get("values", [{}])[0].get("token")
    if not token:
        return {"status": "error", "msg": "Symbol token not found"}

    # ------------------------------
    # 1) Load TPSeries (last 3 days)
    # ------------------------------
    df_raw = ps_api.fetch_full_tpseries(exch, token, interval="5", max_days=3)
    if df_raw is None or df_raw.empty:
        return {"status": "error", "msg": "No TPSeries data"}

    df = df_raw.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime")

    # ------------------------------
    # 2) Apply Indicators
    # ------------------------------
    settings = get_trm_settings_safe()
    df = calc_tkp_trm(df, settings)
    df = calc_pac(df, settings)
    df = calc_atr_trails(df, settings)
    df = calc_macd(df, settings)
    df = calc_gap_move_flag(df)
    df = calc_day_move_flag(df)
    df = calc_intraday_volatility_flag(df)

    last = df.iloc[-1]

    # ------------------------------
    # 3) Apply Strategy Conditions
    # ------------------------------
    if last.get("skip_due_to_gap"):
        return {"status": "blocked", "msg": "GAP FILTER BLOCKED"}

    if last.get("skip_due_to_intraday_vol"):
        return {"status": "blocked", "msg": "VOLATILITY FILTER BLOCKED"}

    if abs(last.get("day_move_pct", 0)) > 1.5:
        return {"status": "blocked", "msg": "DAY MOVE FILTER BLOCKED"}

    # BUY
    if side == "BUY":
        if not (last["trm_signal"] == "Buy" and last["macd"] > last["macd_signal"]):
            return {"status": "blocked", "msg": "BUY conditions not matched"}

    # SELL
    if side == "SELL":
        if not (last["trm_signal"] == "Sell" and last["macd"] < last["macd_signal"]):
            return {"status": "blocked", "msg": "SELL conditions not matched"}

    # ------------------------------
    # 4) CONDITIONS PASSED → ORDER
    # ------------------------------
    order = ps_api.place_order(
        symbol=symbol,
        qty=qty,
        side=side,
        exchange="NSE",
        order_type="MKT",
        product="I"
    )

    return {
        "status": "ok",
        "symbol": symbol,
        "qty": qty,
        "side": side,
        "order": order
    }

# ------------------ Trailing SL loop ------------------
def start_trailing_sl(ps_api, interval=5):
    while True:
        try:
            trade_raw = ps_api.trade_book()
            tb_stat, tb_list = resp_to_status_and_list(trade_raw)

            if not tb_list:
                time.sleep(interval)
                continue

            for pos in tb_list:
                if not isinstance(pos, dict):
                    print(f"⚠️ Skipping unexpected trade_book element: {pos}")
                    continue

                symbol = pos.get("tradingsymbol") or pos.get("tsym") or pos.get("tsym")
                exch = pos.get("exchange") or pos.get("exch") or "NSE"
                try:
                    existing_sl = float(pos.get("stop_loss", 0) or 0.0)
                except Exception:
                    existing_sl = 0.0
                signal_type = "BUY" if (pos.get("buy_or_sell") == "B" or pos.get("trantype") == "B") else "SELL"

                new_sl = pos.get("pac_lower") if signal_type == "BUY" else pos.get("pac_upper")
                if new_sl is None:
                    continue

                try:
                    new_sl = float(new_sl)
                except Exception:
                    continue

                if new_sl and new_sl != existing_sl:
                    try:
                        resp = ps_api.modify_order(
                            norenordno=pos.get("norenordno") or pos.get("norenordno"),
                            tsym=symbol,
                            blprc=new_sl
                        )
                        _, resp_list = resp_to_status_and_list(resp)
                        first = resp_list[0] if resp_list else (resp if isinstance(resp, dict) else None)
                        if isinstance(first, dict) and first.get("stat") == "Ok":
                            print(f"✅ SL updated for {symbol} | Old SL: {existing_sl} -> New SL: {new_sl}")
                        else:
                            emsg = first.get("emsg") if isinstance(first, dict) else str(first)
                            print(f"❌ Failed to update SL for {symbol}: {emsg}")
                    except Exception as e:
                        print(f"❌ Exception updating SL for {symbol}: {e}")

            time.sleep(interval)

        except Exception as e:
            print(f"❌ Error in trailing SL loop: {e}")
            time.sleep(interval)


# -----------------------
# Optimized Parallel Main Runner
# -----------------------
import datetime  # <-- changed import to use datetime.datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import argparse

def main(ps_api=None, args=None, settings=None, symbols=None, place_orders=False):
    if args is None:
        class _A:
            delay_between_calls = 0.25
            max_calls_per_min = 15
            watchlists = "1"
            all_watchlists = False
            interval = "5"
            output = None
            place_orders = False
        args = _A()

    # Force place_orders flag when triggered from dashboard
    if place_orders:
        if args is None:
            class _A:
                watchlists = []
                place_orders = True
                min_volatility = 0.5
                min_price = 100
                max_price = 2000
                skip_no_data = True
            args = _A()
        else:
            setattr(args, "place_orders", True)

    # Login check
    # Login check
    if ps_api is None:
        creds = load_credentials()
        ps_api = ProStocksAPI(
            userid=creds.get("uid"),
            password_plain=creds.get("pwd"),
            vc=creds.get("vc"),
            api_key=creds.get("api_key"),
            imei=creds.get("imei"),
            base_url=creds.get("base_url"),
            apkversion=creds.get("apkversion", "1.0.0")
        )
        if not ps_api.is_logged_in():
            print("❌ Not logged in. Login via dashboard first")
            return []
        print("✅ Logged in successfully via credentials")

  
    # ================================================================
    # ✅ USE ONLY BACKEND-SYNCED TRM SETTINGS (Single Source of Truth)
    # ================================================================

    # ✅ TAKE SETTINGS FROM BACKEND SESSION
    if not hasattr(ps_api, "trm_settings") or not ps_api.trm_settings:
        raise ValueError("❌ TRM settings missing in backend memory. Click 'Start Auto Trader' once.")

    settings = ps_api.trm_settings

    required_keys = [
        "long", "short", "signal",
        "len_rsi", "rsiBuyLevel", "rsiSellLevel",
        "macd_fast", "macd_slow", "macd_signal"
    ]

    missing = [k for k in required_keys if k not in settings]
    if missing:
        raise ValueError(f"❌ TRM settings incomplete in backend, missing: {missing}")

    print("✅ ACTIVE TRM SETTINGS (from BACKEND memory):")
    for k, v in settings.items():
        print(f"   {k} = {v}")

    # ================================================================
    # ✅ Hammer Monitor Thread (ONLY if Streamlit is available)
    # ================================================================
    try:
        import threading
        import streamlit as st

        if hasattr(st, "session_state"):
            if "hammer_thread_started" not in st.session_state:
                threading.Thread(
                    target=monitor_open_positions,
                    args=(ps_api, settings),
                    daemon=True
                ).start()
                st.session_state["hammer_thread_started"] = True
                print("🧠 Hammer Reversal Monitor Thread started ✅")

    except Exception as e:
        print("⚠️ Hammer monitor skipped (CLI mode):", e)

    # Build symbol list
    # ============================================================
    # ⭐ BACKEND TOKEN-MAP MODE: Use tokens sent via /init
    # ============================================================
    if hasattr(ps_api, "_tokens") and ps_api._tokens:
        print("🚀 Using backend-synced token map (from /init)")
        tokens_map = ps_api._tokens
        symbols = list(tokens_map.keys())

        symbols_with_tokens = []
        for sym in symbols:
            tok = tokens_map.get(sym)
            if tok:
                symbols_with_tokens.append({
                    "tsym": sym,
                    "exch": "NSE",
                    "token": tok
                })

        print(f"ℹ️ Symbols with valid tokens (backend mode): {len(symbols_with_tokens)}")

    else:
        
        # ============================================================
        # OLD MODE: Build symbol list from watchlist
        # ============================================================
        symbols_with_tokens = []

        all_symbols = []

        # Load watchlist IDs
        if args and getattr(args, 'all_watchlists', False):
            wls = ps_api.get_watchlists()
            stat, values = resp_to_status_and_list(wls)
            if stat != "Ok":
                print("❌ Failed to list watchlists:", wls)
                return []
            watchlist_ids = sorted(values, key=int)
        else:
            watchlist_ids = [w.strip() for w in (args.watchlists.split(",") if args else []) if w.strip()]

        # Load watchlist items
        for wl in watchlist_ids:
            wl_data = ps_api.get_watchlist(wl)
            wl_stat, wl_list = resp_to_status_and_list(wl_data)
            if wl_stat != "Ok":
                print(f"❌ Could not load watchlist {wl}: {wl_data}")
                continue
            all_symbols.extend(wl_list)

        # FINAL CLEAN SYMBOL TOKEN LIST
        symbols_with_tokens = []
        for s in all_symbols:
            tsym = s.get("tsym")
            token = s.get("token")
            exch = s.get("exch", "NSE")
            if tsym and token:
                symbols_with_tokens.append({
                    "tsym": tsym,
                    "exch": exch,
                    "token": token
                })

        print(f"ℹ️ Symbols with valid tokens: {len(symbols_with_tokens)}")

    results = []
    all_order_responses = []

    start_time = time.time()

    # ============================
    # Parallel Batch Processing 🚀
    # ============================
    MAX_WORKERS = 60  # process 60 stocks at a time
    BATCH_SIZE = 60

    def process_one(sym, ob_list_cache):
        """Wrapper to process and optionally place order"""
        try:
            r = process_symbol(ps_api, sym, args.interval if args else "5", settings)

            # --- Place order only if valid signal and allowed ---
            if r.get("status") == "ok" and r.get("signal") in ["BUY", "SELL"] and getattr(args, 'place_orders', False):

                # ✅ Backend-based skip flag (gap / day move / volatility)
                if r.get("skip_due_to_gap", False):
                    gap_pct = float(r.get("gap_pct", 0))
                    print(f"⏸ Skipping {r['symbol']} due to {gap_pct:.2f}% gap (>1.0%)")
                    all_order_responses.append({
                        "symbol": r['symbol'],
                        "response": {"stat": "Skipped", "emsg": f"Gap {gap_pct:.2f}% > 1.0%"}
                    })
                    return {"symbol": r['symbol'], "response": {"stat": "Skipped", "emsg": f"Gap {gap_pct:.2f}% > 1.0%"}}

                # --- Skip if open order already exists (use cached order book) ---
                open_orders = [
                    o for o in ob_list_cache if isinstance(o, dict)
                    and (o.get("trading_symbol") == r["symbol"] or o.get("tsym") == r["symbol"])
                    and (o.get("status") in ["OPEN", "PENDING", "TRIGGER PENDING"])
                ]
                if open_orders:
                    return {"symbol": r["symbol"], "response": {"stat": "Skipped", "emsg": "Open order exists"}}

                # --- Place the order now ---
                order_resp = place_order_from_signal(ps_api, r)
                return {"symbol": r["symbol"], "response": order_resp}

            else:
                return {"symbol": r.get("symbol"), "response": {"stat": "Skipped", "emsg": "No signal or disabled"}}

        except Exception as e:
            return {"symbol": sym.get("tsym"), "response": {"stat": "Error", "emsg": str(e)}}


    # Run batches
    for i in range(0, len(symbols_with_tokens), BATCH_SIZE):
        batch = symbols_with_tokens[i:i + BATCH_SIZE]
        print(f"\n⚡ Processing batch {i//BATCH_SIZE + 1} ({len(batch)} symbols)...")

        # ✅ Fetch order book once per batch (cache)
        ob_raw = ps_api.order_book()
        ob_stat, ob_list = resp_to_status_and_list(ob_raw)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(process_one, sym, ob_list) for sym in batch]
            for future in as_completed(futures):
                res = future.result()
                results.append(res)
                all_order_responses.append(res)

        # small sleep to avoid API burst
        time.sleep(0.005)

    total_time = round(time.time() - start_time, 2)
    print(f"\n✅ Batch completed for {len(symbols_with_tokens)} symbols in {total_time} sec")

    # Save results
    out_df = pd.DataFrame(results)
    out_file = (args.output if args else None) or f"signals_debug_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out_df.to_csv(out_file, index=False)
    print(f"💾 Saved results to {out_file}")

    return {"results": results, "orders": all_order_responses}
# -------------------------------------------------------
# Alias for Auto Trader compatibility
# -------------------------------------------------------
def batch_main(*args, **kwargs):
    return main(*args, **kwargs)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch TPSeries Screener Debug")
    parser.add_argument("--watchlists", type=str, default="1")
    parser.add_argument("--all-watchlists", action="store_true")
    parser.add_argument("--interval", type=str, default="5")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--max-calls-per-min", type=int, default=15)
    parser.add_argument("--delay-between-calls", type=float, default=0.25)
    parser.add_argument("--place-orders", action="store_true", help="Place orders automatically")
    args = parser.parse_args()

    main(args)


































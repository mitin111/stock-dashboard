#!/usr/bin/env python3
"""
batch_screener_debug.py
Batch TPSeries screener with automatic order placement (BUY/SELL)
Debug-friendly: logs all errors, missing data, session issues, signals, orders.

Usage:
  python batch_screener_debug.py --watchlists 1,2,3 --interval 5 --output signals.csv --place-orders
"""

import os
import time
import argparse
import json
from datetime import datetime
import pandas as pd

from prostocks_connector import ProStocksAPI
from dashboard_logic import place_order_from_signal, load_credentials
import tkp_trm_chart as trm
import threading

# -----------------------------
# ✅ Trade-cycle tracker (1 BUY + 1 SELL per day)
# -----------------------------

def check_trade_cycle_status(ps_api, symbol):
    """
    ✅ Advanced Trade-Cycle Logic
    - BUY→SELL cycle complete → block BUY (SELL open)
    - SELL→BUY cycle complete → block SELL (BUY open)
    - Both cycles complete → full trade lock for the day
    """
    try:
        resp = ps_api.order_book()
        if not resp:
            return {"buy_blocked": False, "sell_blocked": False, "full_lock": False, "last_side": "NONE"}

        all_orders = resp if isinstance(resp, list) else resp.get("data", [])
        if not all_orders:
            return {"buy_blocked": False, "sell_blocked": False, "full_lock": False, "last_side": "NONE"}

        today = datetime.now().strftime("%d-%m-%Y")

        # Filter today's completed orders for this symbol
        orders = [
            o for o in all_orders
            if o.get("tsym") == symbol
            and today in (o.get("norentm") or "")
            and (o.get("status") or "").upper() == "COMPLETE"
        ]
        if not orders:
            return {"buy_blocked": False, "sell_blocked": False, "full_lock": False, "last_side": "NONE"}

        # Sort chronologically
        orders.sort(key=lambda x: x.get("norentm") or "")
        sides = [o.get("trantype") for o in orders if o.get("trantype") in ["B", "S"]]
        if not sides:
            return {"buy_blocked": False, "sell_blocked": False, "full_lock": False, "last_side": "NONE"}

        # Track transitions
        buy_sell_cycle_done = False
        sell_buy_cycle_done = False

        for i in range(1, len(sides)):
            prev, curr = sides[i-1], sides[i]
            if prev == "B" and curr == "S":
                buy_sell_cycle_done = True
            elif prev == "S" and curr == "B":
                sell_buy_cycle_done = True

        last_side = sides[-1]

        # ✅ Decision logic
        full_lock = buy_sell_cycle_done and sell_buy_cycle_done
        buy_blocked = full_lock or buy_sell_cycle_done
        sell_blocked = full_lock or sell_buy_cycle_done

        print(f"📊 {symbol} | LAST={last_side} | BUY_blocked={buy_blocked} | SELL_blocked={sell_blocked} | FULL_LOCK={full_lock}")

        return {
            "buy_blocked": buy_blocked,
            "sell_blocked": sell_blocked,
            "full_lock": full_lock,
            "last_side": last_side
        }

    except Exception as e:
        print(f"⚠️ Error in check_trade_cycle_status({symbol}): {e}")
        return {"buy_blocked": False, "sell_blocked": False, "full_lock": False, "last_side": "NONE"}

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
# Signal generation with debug (Buy above YH / Sell below YL + TSI/MACD confluence + Prev Close filter)
# -----------------------
def generate_signal_for_df(df, settings):
    import datetime
    import pandas as pd

    try:
        df = df.copy()
        df = trm.calc_tkp_trm(df, settings)
        df = trm.calc_macd(df, settings)
        df = trm.calc_pac(df, settings)
        df = trm.calc_atr_trails(df, settings)
        df = trm.calc_yhl(df)  # ✅ ensures y_high, y_low, y_close columns
    except Exception as e:
        print(f"❌ Error calculating indicators for {df.iloc[-1].name if not df.empty else 'unknown'}: {e}")
        print("🔹 Last few rows:\n", df.tail())
        return None

    if len(df) < 2:
        print("⚠️ Not enough candles to compare with previous close")
        return None

    # --- Extract last and previous candle ---
    last = df.iloc[-1]
    prev = df.iloc[-2]

    last_price = float(last.get("close", 0))
    prev_close = float(prev.get("close", 0))
    last_dt = last.get("datetime")

    tsi_sig = last.get("trm_signal", "Neutral")
    macd_hist = float(last.get("macd_hist", 0) or 0)
    pacC = last.get("pacC", None)
    pac_lower = last.get("pacL", None)
    pac_upper = last.get("pacU", None)
    y_high = last.get("y_high", None)
    y_low = last.get("y_low", None)

    # --- Day-level stats ---
    latest_day = df["datetime"].iloc[-1].date()
    day_data = df[df["datetime"].dt.date == latest_day]
    day_high = day_data["high"].max() if not day_data.empty else last_price
    day_low = day_data["low"].min() if not day_data.empty else last_price
    volatility = ((day_high - day_low) / day_low) * 100 if day_low > 0 else 0

    # -------------------------------
    # ✅ Main logic: YH/YL breakout + confluence + last close filter
    # -------------------------------
    reasons, signal = [], None

    if y_high and y_low:
        # --- Step 1: Allow trade only if price still inside yesterday’s range ---
        if not (y_low < last_price < y_high):
            reasons.append(f"⚠️ Price {last_price:.2f} outside yesterday’s range ({y_low:.2f}-{y_high:.2f}), skip entry")
            signal = None
        else:
            # --- Step 2: Breakout above YH / below YL with prev close condition ---
            if last_price > y_high:
                if last_price > prev_close:
                    signal = "BUY"
                    reasons.append(f"Price {last_price:.2f} > YH {y_high:.2f} and > Prev Close {prev_close:.2f}")
                else:
                    reasons.append(f"Skip BUY: Price {last_price:.2f} ≤ Prev Close {prev_close:.2f}")
            elif last_price < y_low:
                if last_price < prev_close:
                    signal = "SELL"
                    reasons.append(f"Price {last_price:.2f} < YL {y_low:.2f} and < Prev Close {prev_close:.2f}")
                else:
                    reasons.append(f"Skip SELL: Price {last_price:.2f} ≥ Prev Close {prev_close:.2f}")
            else:
                # --- Step 3: TSI + MACD confluence within range + prev close filter ---
                if tsi_sig == "Buy" and macd_hist > 0 and (pacC is None or last_price > pacC):
                    if last_price > prev_close:
                        signal = "BUY"
                        reasons.append("TSI=Buy & MACD>0 & Price>PAC mid & >PrevClose")
                    else:
                        reasons.append(f"Skip BUY: Price {last_price:.2f} ≤ Prev Close {prev_close:.2f}")
                elif tsi_sig == "Sell" and macd_hist < 0 and (pacC is None or last_price < pacC):
                    if last_price < prev_close:
                        signal = "SELL"
                        reasons.append("TSI=Sell & MACD<0 & Price<PAC mid & <PrevClose")
                    else:
                        reasons.append(f"Skip SELL: Price {last_price:.2f} ≥ Prev Close {prev_close:.2f}")
                else:
                    signal = None
                    reasons.append("No breakout or confluence match")
    else:
        reasons.append("Missing yesterday high/low values")
        signal = None

    # -------------------------------
    # ✅ Time-based volatility filter
    # -------------------------------
    last_candle_time = pd.to_datetime(df["datetime"].iloc[-1]).time()
    vol_threshold = 1.0

    if datetime.datetime.strptime("09:15", "%H:%M").time() <= last_candle_time < datetime.datetime.strptime("09:20", "%H:%M").time():
        vol_threshold = 1.19
    elif datetime.datetime.strptime("09:20", "%H:%M").time() <= last_candle_time < datetime.datetime.strptime("10:00", "%H:%M").time():
        vol_threshold = 1.29
    elif datetime.datetime.strptime("10:00", "%H:%M").time() <= last_candle_time < datetime.datetime.strptime("11:00", "%H:%M").time():
        vol_threshold = 1.60
    elif datetime.datetime.strptime("11:00", "%H:%M").time() <= last_candle_time < datetime.datetime.strptime("12:00", "%H:%M").time():
        vol_threshold = 2.00
    elif datetime.datetime.strptime("12:00", "%H:%M").time() <= last_candle_time < datetime.datetime.strptime("13:00", "%H:%M").time():
        vol_threshold = 2.20
    elif datetime.datetime.strptime("13:00", "%H:%M").time() <= last_candle_time < datetime.datetime.strptime("14:00", "%H:%M").time():
        vol_threshold = 2.80
    elif datetime.datetime.strptime("14:00", "%H:%M").time() <= last_candle_time <= datetime.datetime.strptime("14:45", "%H:%M").time():
        vol_threshold = 2.80
    elif datetime.datetime.strptime("14:45", "%H:%M").time() <= last_candle_time <= datetime.datetime.strptime("15:25", "%H:%M").time():
        vol_threshold = 2.60

    if volatility < vol_threshold:
        reasons.append(f"Vol {volatility:.2f}% < {vol_threshold}% → skip trade")
        signal = None

    # -------------------------------
    # ✅ Skip if price too far from open
    # -------------------------------
    today_open = day_data["open"].iloc[0] if not day_data.empty else last_price
    price_move_pct = ((last_price - today_open) / today_open) * 100
    if abs(price_move_pct) > 2:
        reasons.append(f"Price moved {price_move_pct:.2f}% from open (>2%), skipping trade")
        signal = None

    # -------------------------------
    # ✅ Stop Loss suggestion
    # -------------------------------
    stop_loss = None
    if signal == "BUY" and pac_lower is not None:
        stop_loss = pac_lower
        reasons.append(f"SL = PAC Lower {pac_lower:.2f}")
    elif signal == "SELL" and pac_upper is not None:
        stop_loss = pac_upper
        reasons.append(f"SL = PAC Upper {pac_upper:.2f}")

    # -------------------------------
    # ✅ Suggested qty by price
    # -------------------------------
    suggested_qty = trm.suggested_qty_by_mapping(last_price)

    # Final cleanup
    if signal not in ["BUY", "SELL"]:
        signal = None

    # -------------------------------
    # ✅ Return final result
    # -------------------------------
    return {
        "signal": signal,
        "reason": " & ".join(reasons),
        "last_price": last_price,
        "last_dt": str(last_dt),
        "stop_loss": stop_loss,
        "suggested_qty": suggested_qty,
        "volatility": round(volatility, 2),
        "pac_lower": pac_lower,
        "pac_upper": pac_upper,
        "y_high": y_high,
        "y_low": y_low,
    }

# ================================================================
# ✅ Dynamic Target/Trail + Auto Order Placement (ProStocks API)
# ================================================================
from datetime import datetime, time
import pytz

def get_dynamic_target_trail(volatility: float):
    """Return (target_pct, trail_pct) based on current time and volatility."""
    volatility = round(float(volatility), 2)
    now = datetime.now(pytz.timezone("Asia/Kolkata")).time()

    def in_range(start, end):
        return start <= now <= end

    # === 09:20–09:30 ===
    if in_range(time(9, 20), time(9, 30)):
        table = [
            (1.2, 1.4, 1.0, 0.5), (1.41, 1.6, 1.3, 0.6), (1.61, 1.8, 1.7, 0.7),
            (1.81, 2.0, 2.0, 0.9), (2.01, 2.2, 2.2, 1.0), (2.21, 2.4, 2.7, 1.1),
            (2.41, 2.6, 3.0, 1.2), (2.61, 2.8, 3.5, 1.5), (2.81, 3.0, 4.0, 1.7),
            (3.01, 999, 4.0, 1.7)
        ]

    elif in_range(time(9, 30), time(10, 0)):
        table = [
            (1.3, 1.4, 1.0, 0.5), (1.41, 1.6, 1.3, 0.6), (1.61, 1.8, 1.7, 0.7),
            (1.81, 2.0, 2.0, 0.9), (2.01, 2.2, 2.2, 1.0), (2.21, 2.4, 2.7, 1.1),
            (2.41, 2.6, 3.0, 1.2), (2.61, 2.8, 3.5, 1.5), (2.81, 3.0, 4.0, 1.7),
            (3.01, 3.2, 4.5, 1.7), (3.21, 999, 5.0, 1.7)
        ]

    elif in_range(time(10, 0), time(11, 0)):
        table = [
            (1.61, 1.8, 1.1, 0.5), (1.81, 2.0, 1.5, 0.7), (2.01, 2.2, 1.7, 0.75),
            (2.21, 2.4, 2.0, 0.85), (2.41, 2.6, 2.5, 1.0), (2.61, 2.8, 2.7, 1.2),
            (2.81, 3.0, 3.0, 1.3), (3.01, 3.2, 3.2, 1.4), (3.21, 999, 3.4, 1.4)
        ]

    elif in_range(time(11, 0), time(12, 0)):
        table = [
            (2.01, 2.2, 1.0, 0.5), (2.21, 2.4, 1.1, 0.6), (2.41, 2.6, 1.3, 0.7),
            (2.61, 2.8, 1.5, 0.7), (2.81, 3.0, 2.0, 0.9), (3.01, 999, 3.0, 1.1)
        ]

    elif in_range(time(12, 0), time(13, 0)):
        table = [
            (2.21, 2.4, 0.75, 0.3), (2.41, 2.6, 0.85, 0.4), (2.61, 2.8, 1.0, 0.5),
            (2.81, 3.0, 1.1, 0.6), (3.01, 999, 1.3, 0.7)
        ]

    elif in_range(time(13, 0), time(14, 0)):
        table = [
            (2.81, 3.0, 1.0, 0.4), (3.01, 999, 1.3, 0.5)
        ]

    elif in_range(time(14, 0), time(14, 45)):
        table = [
            (2.81, 3.0, 1.0, 0.35), (3.01, 999, 1.0, 0.4)
        ]

    else:
        return (None, None)

    for lo, hi, tgt, trail in table:
        if lo <= volatility <= hi:
            return (tgt, trail)

    return (None, None)


# ================================================================
# ✅ Auto Place Order Logic (Bracket Order + Dynamic SL/TP)
# ================================================================
def place_order_from_signal(ps_api, sig):
    symbol = sig.get("symbol")
    signal_type = (sig.get("signal") or "").upper()

    if signal_type not in ["BUY", "SELL"]:
        print(f"⚠️ Skipping order for {symbol}: invalid/neutral signal")
        return [{"stat": "Skipped", "emsg": "No valid signal"}]

    # Step 0: Check existing trade cycle
    cycle = check_trade_cycle_status(ps_api, symbol)
    if signal_type == "BUY" and cycle["buy_cycle_done"]:
        return [{"stat": "Skipped", "emsg": "BUY cycle completed"}]
    if signal_type == "SELL" and cycle["sell_cycle_done"]:
        return [{"stat": "Skipped", "emsg": "SELL cycle completed"}]

    lower_band = sig.get("pac_lower")
    upper_band = sig.get("pac_upper")
    ltp = sig.get("ltp")
    exch = sig.get("exch", "NSE")

    # Step 1: Fetch LTP if missing
    # Step 1: Fetch LTP if missing
    from datetime import datetime, time
    now = datetime.now().time()
    market_open = time(9, 15)
    market_close = time(15, 30)

    if ltp is None:
        try:
            quote_resp = ps_api.get_quotes(symbol, exch)
            if quote_resp and quote_resp.get("stat") == "Ok" and quote_resp.get("lp"):
                ltp = float(quote_resp["lp"])
                sig["ltp"] = ltp
                print(f"📈 {symbol}: Live LTP fetched → {ltp}")
            else:
                # fallback to last known price
                ltp = float(sig.get("last_price") or 0)
                if ltp > 0:
                    print(f"🕒 {symbol}: Using fallback LTP → {ltp}")
                else:
                    if not (market_open <= now <= market_close):
                        print(f"⏳ {symbol}: Market closed ({now.strftime('%H:%M:%S')}) — using no trade mode")
                        return [{"stat": "Skipped", "emsg": "Market closed"}]
                    else:
                        print(f"⚠️ {symbol}: LTP fetch failed — skipping order")
                        return [{"stat": "Skipped", "emsg": "LTP fetch failed"}]
        except Exception as e:
            print(f"⚠️ {symbol}: Exception fetching LTP → {e}")
            ltp = float(sig.get("last_price") or 0)
            if ltp > 0:
                print(f"ℹ️ {symbol}: Using last_price fallback after exception → {ltp}")
            else:
                return [{"stat": "Skipped", "emsg": f"LTP fetch exception: {e}"}]

    # Step 2: PAC validation
    if lower_band is None or upper_band is None:
        print(f"⚠️ {symbol}: Missing PAC band data — skipping order")
        return [{"stat": "Skipped", "emsg": "Missing PAC band"}]

    # Step 3: 2% PAC filter
    if signal_type == "BUY" and ltp > lower_band * 1.02:
        return [{"stat": "Skipped", "emsg": "BUY >2% above lower band"}]
    if signal_type == "SELL" and ltp < upper_band * 0.98:
        return [{"stat": "Skipped", "emsg": "SELL >2% below upper band"}]

    # Step 4: Dynamic SL/TP logic
    vol = float(sig.get("volatility", 0))
    target_pct, trail_pct = get_dynamic_target_trail(vol)
    if target_pct is None:
        print(f"🚫 Skipping {symbol}: no match for vol {vol:.2f}% & current time")
        return [{"stat": "Skipped", "emsg": "No dynamic match"}]

    print(f"🕒 {symbol}: Vol={vol:.2f}% | Target={target_pct}% | Trail={trail_pct}%")

    pac_price = lower_band if signal_type == "BUY" else upper_band
    last_price = float(sig.get("last_price", ltp))
    pac_gap = abs(last_price - pac_price)

    min_sl_rs = last_price * 0.5 / 100
    max_sl_rs = last_price * 1.1 / 100
    sl_gap = min(max(pac_gap, min_sl_rs), max_sl_rs)
    tp_gap = max(last_price * target_pct / 100, min_sl_rs)

    tick = 0.01 if ltp < 200 else 0.05
    blprc = round(sl_gap / tick) * tick
    bpprc = round(tp_gap / tick) * tick
    trail_rs = round(last_price * trail_pct / 100, 2)

    # Step 5: Place Order
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
            remarks=f"Auto BO | Vol={vol:.2f}% | Tgt={target_pct}% | Trail={trail_pct}%"
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


# -----------------------
# Per-symbol processing
# -----------------------
def process_symbol(ps_api, symbol_obj, interval, settings):
    exch = symbol_obj.get("exch", "NSE")
    token = str(symbol_obj.get("token"))
    tsym = symbol_obj.get("tsym") or symbol_obj.get("tradingsymbol") or f"{exch}|{token}"

    result = {"symbol": tsym, "exch": exch, "token": token, "status": "unknown"}

    try:
        df = ps_api.fetch_full_tpseries(exch, token, interval)
    except Exception as e:
        result.update({"status": "error_fetch_tp", "emsg": str(e)})
        print(f"❌ [{tsym}] TPSeries fetch error: {e}")
        return result

    if isinstance(df, dict):
        result.update({"status": "error_fetch_tp", "emsg": json.dumps(df)})
        print(f"❌ [{tsym}] TPSeries returned dict error: {df}")
        return result
    if df.empty:
        result.update({"status": "no_data"})
        print(f"⚠️ [{tsym}] No TPSeries data")
        return result

    if "into" in df.columns and "open" not in df.columns:
        df = df.rename(columns={
            "into": "open",
            "inth": "high",
            "intl": "low",
            "intc": "close",
            "intv": "volume"
        })

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])

    df = tz_normalize_df(df)
    if df.empty:
        result.update({"status": "no_data_after_norm"})
        print(f"⚠️ [{tsym}] No data after timezone normalization")
        return result

    print(f"🔹 Debug [{tsym}] DF head:\n", df.head())
    print(f"🔹 Debug [{tsym}] DF columns:\n", df.columns)

    sig = generate_signal_for_df(df, settings)
    if sig is None:
        result.update({"status": "no_signal"})
        print(f"⚠️ [{tsym}] Signal generation failed")
        return result

    result.update({
        "yclose": df["close"].iloc[-2] if len(df) > 1 else df["close"].iloc[-1],
        "open": df["open"].iloc[-1]
    })

    last_candle_time = pd.to_datetime(df["datetime"].iloc[-1])
    if last_candle_time.strftime("%H:%M") == "09:15":
        result.update({"status": "skip_first_candle"})
        print(f"⏸ [{tsym}] Skipping trade on first candle of the day ({last_candle_time})")
        return result

    result.update({"status": "ok", **sig})
    return result


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
# Main runner
# -----------------------
def main(args=None, ps_api=None, settings=None, symbols=None, place_orders=False):
    if args is None:
        # create a safe args-like object with sane defaults for interactive use
        class _A:
            delay_between_calls = 0.25
            max_calls_per_min = 15
            watchlists = "1"
            all_watchlists = False
            interval = "5"
            output = None
            place_orders = False
        args = _A()

    # --- Fix: ensure dashboard place_orders=True overrides default args ---
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

    if ps_api is None:
        creds = load_credentials()
        ps_api = ProStocksAPI(**creds)
        if not ps_api.is_logged_in():
            print("❌ Not logged in. Login via dashboard first")
            return []
        print("✅ Logged in successfully via credentials")

    if settings is None:
        try:
            import streamlit as st
            settings = st.session_state.get("strategy_settings")
        except Exception:
            settings = None

        if not settings:
            raise ValueError("❌ TRM settings missing in session_state! Cannot proceed without explicit settings.")

        required_keys = ["long", "short", "signal_length", "macd_fast", "macd_slow", "macd_signal"]
        missing = [k for k in required_keys if k not in settings]
        if missing:
            raise ValueError(f"❌ TRM settings incomplete, missing keys: {missing}")

        print("🔹 Loaded TRM settings for Auto Trader:", settings)

    symbols_with_tokens = []
    if symbols:
        for s in symbols:
            symbols_with_tokens.append({
                "tsym": s.get("tsym") if isinstance(s, dict) else s,
                "exch": s.get("exch", "NSE") if isinstance(s, dict) else "NSE",
                "token": s.get("token", "") if isinstance(s, dict) else ""
            })
    else:
        all_symbols = []
        if args and getattr(args, 'all_watchlists', False):
            wls = ps_api.get_watchlists()
            stat, values = resp_to_status_and_list(wls)
            if stat != "Ok":
                print("❌ Failed to list watchlists:", wls)
                return []
            watchlist_ids = sorted(values, key=int)
        else:
            watchlist_ids = [w.strip() for w in (args.watchlists.split(",") if args else []) if w.strip()]

        for wl in watchlist_ids:
            wl_data = ps_api.get_watchlist(wl)
            wl_stat, wl_list = resp_to_status_and_list(wl_data)
            if wl_stat != "Ok":
                print(f"❌ Could not load watchlist {wl}: {wl_data}")
                continue
            all_symbols.extend(wl_list)

        for s in all_symbols:
            token = s.get("token", "")
            if token:
                symbols_with_tokens.append({
                    "tsym": s.get("tsym"),
                    "exch": s.get("exch", "NSE"),
                    "token": token
                })

    print(f"ℹ️ Symbols with valid tokens: {len(symbols_with_tokens)}")

   
    results = []
    all_order_responses = []

    calls_made, window_start = 0, time.time()
    MAX_CALLS_PER_MIN = 150
    DELAY_BETWEEN_CALLS = 0.01  # minimal delay

    for idx, sym in enumerate(symbols_with_tokens, 1):
        calls_made += 1
        elapsed = time.time() - window_start

        # Rate-limit check
        if calls_made > MAX_CALLS_PER_MIN:
            to_wait = max(0, 60 - elapsed)
            print(f"⏱ Rate limit reached. Sleeping {to_wait:.1f}s")
            time.sleep(to_wait)
            window_start, calls_made = time.time(), 1

        print(f"\n🔹 [{idx}/{len(symbols_with_tokens)}] Processing {sym['tsym']} ...")

        # Process symbol
        try:
            r = process_symbol(ps_api, sym, args.interval if args else "5", settings)
        except Exception as e:
            r = {"symbol": sym.get("tsym"), "status": "exception", "emsg": str(e)}
            print(f"❌ Exception for {sym.get('tsym')}: {e}")

        results.append(r)
        time.sleep(DELAY_BETWEEN_CALLS)


        # ---------------- Order placement ----------------
        if r.get("status") == "ok" and r.get("signal") in ["BUY", "SELL"] and getattr(args, 'place_orders', False):
            try:
                yclose = float(r.get("yclose", 0))
                oprice = float(r.get("open", 0))
                if yclose > 0 and oprice > 0:
                    gap_pct = ((oprice - yclose) / yclose) * 100
                    if abs(gap_pct) > 1.0:
                        print(f"⏸ Skipping {r['symbol']} due to {gap_pct:.2f}% gap (yclose={yclose}, open={oprice})")
                        all_order_responses.append({
                            "symbol": r['symbol'],
                            "response": {"stat": "Skipped", "emsg": f"Gap {gap_pct:.2f}% > 1.0%"}
                        })
                        time.sleep(getattr(args, 'delay_between_calls', 0.25))
                        continue

                # --- Check if symbol already has an open order ---
                ob_raw = ps_api.order_book()
                ob_stat, ob_list = resp_to_status_and_list(ob_raw)

                open_orders = []
                for order in ob_list:
                    if not isinstance(order, dict):
                        continue
                    ts = (
                        order.get("trading_symbol")
                        or order.get("tsym")
                        or order.get("symbol")
                    )
                    status = (
                        order.get("status")
                        or order.get("st_intrn")
                        or order.get("stat")
                    )

                    if ts == r["symbol"] and status in ["OPEN", "PENDING", "TRIGGER PENDING"]:
                        open_orders.append(order)

                if open_orders:
                    print(f"⚠️ Skipping {r['symbol']}: already has {len(open_orders)} open order(s)")
                    all_order_responses.append({
                        "symbol": r["symbol"],
                        "response": {"stat": "Skipped", "emsg": "Open order exists"}
                    })
                    time.sleep(getattr(args, 'delay_between_calls', 0.25))
                    continue

                order_resp = place_order_from_signal(ps_api, r)
                all_order_responses.append({"symbol": r["symbol"], "response": order_resp})
                print(f"🚀 Order placed for {r['symbol']}: {order_resp}")

                # mark if any OK
                # order_resp can be list/dict
                if isinstance(order_resp, dict) and order_resp.get('stat') == 'Ok':
                    order_placed = True
                elif isinstance(order_resp, list):
                    for it in order_resp:
                        if isinstance(it, dict) and it.get('stat') == 'Ok':
                            order_placed = True
                            break

            except Exception as e:
                all_order_responses.append({
                    "symbol": r['symbol'],
                    "response": {"stat": "Exception", "emsg": str(e)}
                })
                print(f"❌ Order placement failed for {r['symbol']}: {e}")

            # rate limit delay between order calls
            time.sleep(getattr(args, 'delay_between_calls', 0.25))

        else:
            print(f"⏸ Skipping {r['symbol']} due to invalid signal or place_orders disabled: {r.get('signal')}")
            all_order_responses.append({
                "symbol": r['symbol'],
                "response": {"stat": "Skipped", "emsg": f"Invalid signal {r.get('signal') or 'None'} or place_orders disabled"}
            })
            time.sleep(getattr(args, 'delay_between_calls', 0.25))

    # Save results
    out_df = pd.DataFrame(results)
    out_file = (args.output if args else None) or f"signals_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out_df.to_csv(out_file, index=False)
    print(f"✅ Saved results to {out_file}")

    if "signal" in out_df.columns:
        print("\nSummary Signals:\n", out_df["signal"].value_counts(dropna=False))

    # ---------------- Skip trailing SL thread for Bracket Orders ----------------
    if getattr(args, 'place_orders', False) and order_placed:
        # ✅ Since we are placing only Bracket Orders (product_type='B'),
        # no need to run trailing SL loop — handled internally by RMS.
        print("✅ Skipping trailing SL thread (Bracket Orders manage SL internally).")

    return {
        "results": results,
        "orders": all_order_responses
    }


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






























































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

    # --- Volatility calculation (today's candles) ---
    latest_day = df["datetime"].iloc[-1].date()
    day_data = df[df["datetime"].dt.date == latest_day]
    day_high = day_data["high"].max() if not day_data.empty else last_price
    day_low = day_data["low"].min() if not day_data.empty else last_price
    volatility = ((day_high - day_low) / day_low) * 100 if day_low > 0 else 0

    reasons, signal = [], None

    # ✅ Strong BUY
    if tsi_sig == "Buy" and macd_hist > 0 and (pacC is None or last_price > pacC):
        signal = "BUY"
        reasons.append("TSI=Buy & MACD hist >0")
        if pacC is not None:
            reasons.append("Price > PAC mid")

    # ✅ Strong SELL
    elif tsi_sig == "Sell" and macd_hist < 0 and (pacC is None or last_price < pacC):
        signal = "SELL"
        reasons.append("TSI=Sell & MACD hist <0")
        if pacC is not None:
            reasons.append("Price < PAC mid")

    # ✅ Weak Neutral but log reason
    else:
        if tsi_sig == "Neutral" and macd_hist != 0:
            reasons.append(f"Weak confluence: TSI Neutral, MACD {'pos' if macd_hist>0 else 'neg'}")
        else:
            reasons.append("No confluence")

    # --- Apply volatility filter: only allow BUY/SELL if >2% ---
    if volatility < 2:
        signal = "NEUTRAL"
        reasons.append(f"Volatility {volatility:.2f}% < 2%, skipping trade")

    # --- 2% move from today's open check ---
    today_open = day_data["open"].iloc[0] if not day_data.empty else last_price
    price_move_pct = ((last_price - today_open) / today_open) * 100
    if abs(price_move_pct) > 2:
        signal = None
        reasons.append(f"Price moved {price_move_pct:.2f}% from today's open (>2%), skipping trade")

    # ✅ Stoploss calculation using PAC bands
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

# -----------------------
# Place order from signal
# -----------------------
def place_order_from_signal(ps_api, sig):
    """
    Place Intraday Bracket BUY/SELL orders with SL from PAC bands
    """
    signal_type = sig.get("signal") if sig else None
    if not signal_type or signal_type.upper() not in ["BUY", "SELL"]:
        print(f"⚠️ Skipping order: invalid/neutral signal for {sig.get('symbol') if sig else 'unknown'}")
        return {"stat": "Skipped", "emsg": "No valid signal"}
    signal_type = signal_type.upper()
    
    qty = sig.get("suggested_qty", 1)
    last_price = float(sig.get("last_price", 0))
    exch = sig.get("exch", "NSE")
    symbol = sig.get("symbol")

    # ✅ Bracket order product
    product_type = "B"
    price_type = "MKT"
    price = 0.0  

    # --- Stoploss from PAC bands ---
    pac_lower = sig.get("pac_lower")
    pac_upper = sig.get("pac_upper")

    # ✅ Replace with PAC stoploss
    if signal_type == "BUY":
        new_sl = pos.get("pac_lower")
        
    elif signal_type == "SELL":
        new_sl = pos.get("pac_upper")
    else:
        new_sl = None
    try:
        resp = ps_api.place_order(
            buy_or_sell="B" if signal_type == "BUY" else "S",
            product_type=product_type,
            exchange=exch,
            tradingsymbol=symbol,
            quantity=qty,
            discloseqty=0,
            price_type=price_type,
            price=price,
            trgprc=stop_loss,     # ✅ PAC-based Stoploss
            bpprc=target_price,  # ✅ Target
            remarks="Auto Bracket Order with PAC SL"
        )
        if resp.get("stat") == "Ok":
            print(f"✅ BO placed for {symbol} | {signal_type} | Qty={qty} | SL={stop_loss} | TP={target_price}")
        else:
            print(f"❌ BO failed for {symbol}: {resp.get('emsg')}")
        return resp
    
    except Exception as e:
        print(f"❌ Exception placing BO for {symbol}: {e}")
        return {"stat": "Exception", "emsg": str(e)}

      
# -----------------------
# Per-symbol processing
# -----------------------
def process_symbol(ps_api, symbol_obj, interval, settings):
    exch = symbol_obj.get("exch", "NSE")
    token = str(symbol_obj.get("token"))
    tsym = symbol_obj.get("tsym") or symbol_obj.get("tradingsymbol") or f"{exch}|{token}"

    result = {"symbol": tsym, "exch": exch, "token": token, "status": "unknown"}

    # Fetch TPSeries data
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

    # --- CONVERSION TO NUMERIC ---
    if "into" in df.columns and "open" not in df.columns:
        df = df.rename(columns={
            "into": "open",
            "inth": "high",
            "intl": "low",
            "intc": "close",
            "intv": "volume"
        })

    # Convert OHLCV columns to numeric
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # Drop rows with NaN in critical columns
    df = df.dropna(subset=["open", "high", "low", "close"])

    # Timezone normalization
    df = tz_normalize_df(df)
    if df.empty:
        result.update({"status": "no_data_after_norm"})
        print(f"⚠️ [{tsym}] No data after timezone normalization")
        return result

    # --- DEBUG: Print DF head and columns before indicator calculation ---
    print(f"🔹 Debug [{tsym}] DF head:\n", df.head())
    print(f"🔹 Debug [{tsym}] DF columns:\n", df.columns)

    # Generate signal
    sig = generate_signal_for_df(df, settings)
    if sig is None:
        result.update({"status": "no_signal"})
        print(f"⚠️ [{tsym}] Signal generation failed")
        return result

    # ✅ Add yesterday close & today open
    result.update({
        "yclose": df["close"].iloc[-2] if len(df) > 1 else df["close"].iloc[-1],
        "open": df["open"].iloc[-1]
    })

    # ✅ Skip first candle of the day
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
            trade_book = ps_api.trade_book()
            if not trade_book:
                time.sleep(interval)
                continue

            for pos in trade_book:
                symbol = pos.get("tradingsymbol")
                exch = pos.get("exchange", "NSE")
                existing_sl = float(pos.get("stop_loss", 0) or 0.0)
                signal_type = "BUY" if pos.get("buy_or_sell") == "B" else "SELL"

                # ✅ PAC stoploss logic
                if signal_type == "BUY":
                    new_sl = pos.get("pac_lower")
                else:
                    new_sl = pos.get("pac_upper")

                if new_sl and new_sl != existing_sl:
                    try:
                        resp = ps_api.modify_order(
                            norenordno=pos.get("norenordno"),
                            tsym=symbol,
                            blprc=new_sl
                        )
                        if resp.get("stat") == "Ok":
                            print(f"✅ SL updated for {symbol} | Old SL: {existing_sl} -> New SL: {new_sl}")
                        else:
                            print(f"❌ Failed to update SL for {symbol}: {resp.get('emsg')}")
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
    """
    Auto Trader batch runner.
    place_orders: Streamlit ke liye explicit order trigger flag.
    """
    if ps_api is None:
        creds = load_credentials()
        ps_api = ProStocksAPI(**creds)
        if not ps_api.is_logged_in():
            print("❌ Not logged in. Login via dashboard first")
            return []
        print("✅ Logged in successfully via credentials")

    if settings is None:
        # ✅ Use only session_state settings, do NOT load defaults
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

    # ---------------- Symbol resolution ----------------
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
        if args and args.all_watchlists:
            wls = ps_api.get_watchlists()
            if wls.get("stat") != "Ok":
                print("❌ Failed to list watchlists:", wls)
                return []
            watchlist_ids = sorted(wls["values"], key=int)
        else:
            watchlist_ids = [w.strip() for w in (args.watchlists.split(",") if args else []) if w.strip()]

        for wl in watchlist_ids:
            wl_data = ps_api.get_watchlist(wl)
            if wl_data.get("stat") != "Ok":
                print(f"❌ Could not load watchlist {wl}: {wl_data.get('emsg')}")
                continue
            all_symbols.extend(wl_data.get("values", []))

        for s in all_symbols:
            token = s.get("token", "")
            if token:
                symbols_with_tokens.append({
                    "tsym": s.get("tsym"),
                    "exch": s.get("exch", "NSE"),
                    "token": token
                })

    print(f"ℹ️ Symbols with valid tokens: {len(symbols_with_tokens)}")

    # ---------------- Run screener ----------------
    results = []
    all_order_responses = []
    calls_made, window_start = 0, time.time()

    for idx, sym in enumerate(symbols_with_tokens, 1):
        calls_made += 1
        elapsed = time.time() - window_start
        if args and calls_made > args.max_calls_per_min:
            to_wait = max(0, 60 - elapsed) + 0.5
            print(f"⏱ Rate limit reached. Sleeping {to_wait:.1f}s")
            time.sleep(to_wait)
            window_start, calls_made = time.time(), 1

        print(f"\n🔹 [{idx}/{len(symbols_with_tokens)}] Processing {sym['tsym']} ...")
        try:
            r = process_symbol(ps_api, sym, args.interval if args else "5", settings)
        except Exception as e:
            r = {"symbol": sym.get("tsym"), "status": "exception", "emsg": str(e)}
            print(f"❌ Exception for {sym.get('tsym')}: {e}")
        results.append(r)

        # ---------------- Order placement ----------------
        if r.get("status") == "ok" and r.get("signal") in ["BUY", "SELL"]:
            try:
                # --- Gap filter check ---
                yclose = float(r.get("yclose", 0))
                oprice = float(r.get("open", 0))
                if yclose > 0 and oprice > 0:
                    gap_pct = ((oprice - yclose) / yclose) * 100
                    if abs(gap_pct) > 2:
                        print(f"⏸ Skipping {r['symbol']} due to {gap_pct:.2f}% gap (yclose={yclose}, open={oprice})")
                        all_order_responses.append({
                            "symbol": r['symbol'],
                            "response": {"stat": "Skipped", "emsg": f"Gap {gap_pct:.2f}% > 2%"}
                        })
                        continue
                      
                # --- Check if symbol already has an open order ---
                ob = ps_api.order_book() or {}
                open_orders = []
                if ob.get("stat") == "Ok":
                    for order in ob.get("data", []):
                        if (
                            order.get("trading_symbol") == r['symbol'] and 
                            order.get("status") in ["OPEN", "PENDING", "TRIGGER PENDING"]
                        ):
                            open_orders.append(order)

                if open_orders:
                    print(f"⚠️ Skipping {r['symbol']}: already has {len(open_orders)} open order(s)")
                    all_order_responses.append({
                        "symbol": r['symbol'],
                        "response": {"stat": "Skipped", "emsg": "Open order exists"}
                    })
                    continue
                  
                order_resp = place_order_from_signal(ps_api, r)
                all_order_responses.append({"symbol": r['symbol'], "response": order_resp})
                print(f"🚀 Order placed for {r['symbol']}: {order_resp}")
            except Exception as e:
                all_order_responses.append({
                    "symbol": r['symbol'],
                    "response": {"stat": "Exception", "emsg": str(e)}
                })
                print(f"❌ Order placement failed for {r['symbol']}: {e}")
        else:
            print(f"⏸ Skipping {r['symbol']} due to invalid signal: {r.get('signal')}")
            all_order_responses.append({
                "symbol": r['symbol'],
                "response": {"stat": "Skipped", "emsg": f"Invalid signal {r.get('signal')}"}
            })  
              
        if args:
            time.sleep(args.delay_between_calls)

    # Save results
    out_df = pd.DataFrame(results)
    out_file = (args.output if args else None) or f"signals_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out_df.to_csv(out_file, index=False)
    print(f"✅ Saved results to {out_file}")

    if "signal" in out_df.columns:
        print("\nSummary Signals:\n", out_df["signal"].value_counts(dropna=False))

    # ---------------- Order placement loop me, valid order ke baad
    order_placed = False
    for r in results:
        if r.get("status") == "ok" and r.get("signal") in ["BUY", "SELL"]:
            resp = place_order_from_signal(ps_api, r)
            all_order_responses.append({"symbol": r['symbol'], "response": resp})
            if resp.get("stat") == "Ok":
                order_placed = True

    # ---------------- Start trailing SL thread only if at least 1 order placed
    if args and args.place_orders and order_placed:
        t = threading.Thread(target=start_trailing_sl, args=(ps_api, 5), daemon=True)
        t.start()
        print("📡 Trailing SL thread started in background...")

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









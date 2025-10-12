# dashboard_logic.py

# dashboard_logic.py

import os
import json
import time
import threading
import pandas as pd
import streamlit as st
from datetime import datetime, time
from dotenv import load_dotenv

SETTINGS_FILE = "dashboard_settings.json"
QTY_MAP_FILE = "qty_map.json"

# === Load general dashboard settings (auto buy/sell, timings etc.)
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
            for k in ["trading_start", "trading_end", "cutoff_time", "auto_exit_time"]:
                if k in data:
                    data[k] = datetime.strptime(data[k], "%H:%M").time()
            return data
    return {
        "master_auto": True,
        "auto_buy": True,
        "auto_sell": True,
        "trading_start": time(9, 15),
        "trading_end": time(15, 15),
        "cutoff_time": time(14, 50),
        "auto_exit_time": time(15, 12)
    }

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

# === Qty Map (Q1..Q6)
def save_qty_map(qty_map: dict):
    with open(QTY_MAP_FILE, "w") as f:
        json.dump(qty_map, f)

def load_qty_map() -> dict:
    if os.path.exists(QTY_MAP_FILE):
        try:
            with open(QTY_MAP_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    # Default quantity mapping (Q1–Q11)
    return {
        "Q1": 1, "Q2": 1, "Q3": 1, "Q4": 1, "Q5": 1,
        "Q6": 1, "Q7": 1, "Q8": 1, "Q9": 1, "Q10": 1, "Q11": 1
    }

# === Load ProStocks credentials
def load_credentials():
    load_dotenv()
    return {
        "uid": os.getenv("PROSTOCKS_USER_ID", ""),
        "pwd": os.getenv("PROSTOCKS_PASSWORD", ""),
        "factor2": os.getenv("PROSTOCKS_FACTOR2", ""),
        "vc": os.getenv("PROSTOCKS_VENDOR_CODE", ""),
        "api_key": os.getenv("PROSTOCKS_API_KEY", ""),
        "imei": os.getenv("PROSTOCKS_MAC", "MAC123456"),
        "base_url": os.getenv("PROSTOCKS_BASE_URL", "https://starapi.prostocks.com/NorenWClientTP"),
        "apkversion": os.getenv("PROSTOCKS_APK_VERSION", "1.0.0"),
    }

# === Order placement helper
def place_order_from_signal(ps_api, result):
    """
    Places order via ProStocksAPI using signal dict from batch_screener.
    result = {
        'symbol': 'CANBK-EQ', 'signal': 'BUY', 'last_price': 123,
        'suggested_qty': 8, 'exch': 'NSE', ...
    }
    """
    signal = result.get("signal")
    tsym = result.get("symbol")
    exch = result.get("exch")
    qty = int(result.get("suggested_qty", 1))
    price = float(result.get("last_price", 0))

    if signal not in ["BUY", "SELL"]:
        print(f"⚠️ Skipping NEUTRAL signal for {tsym}")
        return None

    trantype = "B" if signal == "BUY" else "S"

    # ✅ Replace dict call with keyword-argument style
    try:
        print(f"🔹 Placing order: {tsym} {signal} qty={qty} price={price}")
        resp = ps_api.place_order(
            buy_or_sell=trantype,
            product_type="C",            # Cash segment
            exchange=exch,
            tradingsymbol=tsym,
            quantity=qty,
            discloseqty=0,
            price_type="LMT" if price > 0 else "MKT",
            price=price if price > 0 else 0.0,
            remarks=f"batch_screener_{signal}"
        )
        print(f"✅ Order response: {resp}")
        return resp
    except Exception as e:
        print(f"❌ Order failed for {tsym}: {e}")
        return None

# === Live engine helper: preload TPSeries + start WebSocket ===
def start_live_engine(ps_api, watchlist_id, interval, ui_queue):
    """Fetch TPSeries for the watchlist and start websocket in background."""

    # --- TPSeries preload ---
    try:
        tpseries_results = ps_api.fetch_tpseries_for_watchlist(watchlist_id, interval)
    except Exception as e:
        ui_queue.put(("tp_error", str(e)))
        return

    if tpseries_results:
        try:
            df = tpseries_results[0]["data"].copy()
            if "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
                df["datetime"] = df["datetime"].dt.tz_localize(
                    "Asia/Kolkata", nonexistent="shift_forward", ambiguous="NaT"
                )
                df = df.dropna(subset=["datetime"]).set_index("datetime")

                if "into" in df.columns and "open" not in df.columns:
                    df = df.rename(
                        columns={"into": "open", "inth": "high", "intl": "low", "intc": "close", "intv": "volume"}
                    )

                for col in ["open", "high", "low", "close", "volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                df = df.dropna(subset=["open", "high", "low", "close"])

                # 👉 Instead of touching session_state, push to queue
                ui_queue.put(("tp_loaded", df))
        except Exception as e:
            ui_queue.put(("tp_error", str(e)))
    else:
        ui_queue.put(("tp_empty", "No TPSeries data"))

    # --- WebSocket start ---
    try:
        wl_data = ps_api.get_watchlist(watchlist_id)
        scrips = wl_data.get("values", []) if isinstance(wl_data, dict) else []
        symbols_for_ws = [f"{s['exch']}|{s['token']}" for s in scrips]

        if symbols_for_ws:
            def on_tick_callback(tick):
                try:
                    ui_queue.put(("tick", tick))
                except Exception:
                    pass

            ws = ps_api.connect_websocket(symbols_for_ws, on_tick=on_tick_callback, tick_file="ticks_tab5.log")

            def heartbeat_loop():
                while True:
                    try:
                        ws.send("ping")
                        hb = datetime.now().strftime("%H:%M:%S")
                        ui_queue.put(("heartbeat", hb))
                    except Exception:
                        break
                    time.sleep(20)

            threading.Thread(target=heartbeat_loop, daemon=True).start()
            ui_queue.put(("ws_started", {"symbols": len(symbols_for_ws)}))
        else:
            ui_queue.put(("ws_empty", "No symbols for websocket"))
    except Exception as e:
        ui_queue.put(("ws_error", str(e)))





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
    return {"Q1": 10, "Q2": 20, "Q3": 30, "Q4": 40, "Q5": 50, "Q6": 60}

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
    signal = result.get("signal")
    tsym = result.get("symbol")
    exch = result.get("exch")
    qty = result.get("suggested_qty", 1)
    price = result.get("last_price", 0)

    if signal not in ["BUY", "SELL"]:
        return None

    bos = "B" if signal == "BUY" else "S"

    try:
        print(f"🔹 Trying to place order: {tsym} signal={signal} qty={qty} price={price}")
        order = ps_api.place_order(
            buy_or_sell=bos,
            product_type="C",
            exchange=exch,
            tradingsymbol=tsym,
            quantity=qty,
            discloseqty=0,
            price_type="MKT",
            price=price,
            trigger_price=None,
            retention="DAY",
            remarks=f"batch_screener_{signal}"
        )
        print(f"✅ Order placed for {tsym}: {signal} x {qty}")
        return order
    except Exception as e:
        print(f"❌ Order failed for {tsym}: {e}")
        return None


# === Live engine helper: preload TPSeries + start WebSocket ===
def start_live_engine(ps_api, watchlist_id, interval, ui_queue):
    """Fetch TPSeries for the watchlist and start websocket in background."""
    try:
        tpseries_results = ps_api.fetch_tpseries_for_watchlist(watchlist_id, interval)
    except Exception as e:
        ui_queue.put(("tp_error", str(e)), block=False)
        return

    if tpseries_results:
        try:
            df = tpseries_results[0]["data"].copy()
            if "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
                df["datetime"] = df["datetime"].dt.tz_localize("Asia/Kolkata", nonexistent="shift_forward", ambiguous="NaT")
                df = df.dropna(subset=["datetime"]).set_index("datetime")
                if "into" in df.columns and "open" not in df.columns:
                    df = df.rename(columns={"into": "open", "inth": "high", "intl": "low", "intc": "close", "intv": "volume"})
                for col in ["open","high","low","close","volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(subset=["open","high","low","close"])

                st.session_state.ohlc_x = list(df.index)
                st.session_state.ohlc_o = list(df["open"].astype(float))
                st.session_state.ohlc_h = list(df["high"].astype(float))
                st.session_state.ohlc_l = list(df["low"].astype(float))
                st.session_state.ohlc_c = list(df["close"].astype(float))
                st.session_state.last_tp_dt = st.session_state.ohlc_x[-1] if st.session_state.ohlc_x else None
                ui_queue.put(("tp_loaded", {"count": len(df)}), block=False)
        except Exception as e:
            ui_queue.put(("tp_error", str(e)), block=False)
    else:
        ui_queue.put(("tp_empty", "No TPSeries data"), block=False)

    # Start WebSocket
    try:
        wl_data = ps_api.get_watchlist(watchlist_id)
        scrips = wl_data.get("values", []) if isinstance(wl_data, dict) else []
        symbols_for_ws = [f"{s['exch']}|{s['token']}" for s in scrips]

        if symbols_for_ws:
            st.session_state.symbols_for_ws = symbols_for_ws
            st.session_state.ws_started = True
            st.session_state.live_feed_flag["active"] = True

            def on_tick_callback(tick):
                try:
                    ui_queue.put(("tick", tick), block=False)
                except Exception:
                    pass

            ws = ps_api.connect_websocket(symbols_for_ws, on_tick=on_tick_callback, tick_file="ticks_tab5.log")

            def heartbeat_loop():
                while st.session_state.get("live_feed_flag", {}).get("active", False):
                    try:
                        ws.send("ping")
                        hb = datetime.now().strftime("%H:%M:%S")
                        ui_queue.put(("heartbeat", hb), block=False)
                    except Exception:
                        break
                    time.sleep(20)
            threading.Thread(target=heartbeat_loop, daemon=True).start()
            ui_queue.put(("ws_started", {"symbols": len(symbols_for_ws)}), block=False)
        else:
            ui_queue.put(("ws_empty", "No symbols for websocket"), block=False)
    except Exception as e:
        ui_queue.put(("ws_error", str(e)), block=False)

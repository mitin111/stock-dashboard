# tab4_auto_trader.py
import streamlit as st
import pandas as pd
import threading
import time
import queue
from tkp_trm_chart import load_trm_settings_from_file
from dashboard_logic import save_qty_map, load_qty_map
import json

# 🔹 Global queue for thread -> UI communication
ui_queue = queue.Queue()
AUTO_TRADE_FLAG = False
strategy_settings_copy = None

# Helper: safe print (so it shows in server logs)
def log(*args, **kwargs):
    print(*args, **kwargs)

def render_tab4(require_session_settings=False, allow_file_fallback=True):
    """
    Render the Indicator Settings / Auto Trader control UI (Tab 4).
    - require_session_settings: if True, do NOT use file fallback; settings must be in st.session_state["strategy_settings"].
    - allow_file_fallback: when False, never read settings from file.
    """
    st.subheader("📦 Position Quantity Mapping")

    # Load saved qty_map (agar None ya corrupt ho to default dict lo)
    current_map = load_qty_map()
    if not isinstance(current_map, dict):
        current_map = {}

    q1 = st.number_input("Q1 (170-200)", min_value=1, value=current_map.get("Q1", 1), key="q1_input")
    q2 = st.number_input("Q2 (201-400)", min_value=1, value=current_map.get("Q2", 1), key="q2_input")
    q3 = st.number_input("Q3 (401-600)", min_value=1, value=current_map.get("Q3", 1), key="q3_input")
    q4 = st.number_input("Q4 (601-800)", min_value=1, value=current_map.get("Q4", 1), key="q4_input")
    q5 = st.number_input("Q5 (801-1000)", min_value=1, value=current_map.get("Q5", 1), key="q5_input")
    q6 = st.number_input("Q6 (Above 1000)", min_value=1, value=current_map.get("Q6", 1), key="q6_input")

    qty_map = {"Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4, "Q5": q5, "Q6": q6}

    # Save button
    if st.button("💾 Save Quantity Mapping"):
        try:
            save_qty_map(qty_map)
            st.success("✅ Quantity mapping saved (persistent).")
        except Exception as e:
            st.error(f"❌ Could not save qty map: {e}")

    st.write("📌 Current Quantity Mapping:", qty_map)

    # === UI Polling for Live Engine Events (ui_queue) ===
    # === UI Polling for Live Engine Events (ui_queue) ===
    import queue, threading, time
    from datetime import datetime
    from tab4_auto_trader import start_ws   # ✅ your WS starter

    # --- Queue & WS Init ---
    if "ui_queue" not in st.session_state:
        st.session_state["ui_queue"] = queue.Queue()

    if "_ws_stop_event" not in st.session_state:
        st.session_state["_ws_stop_event"] = threading.Event()

    # start websocket only once
    if "ws" not in st.session_state or st.session_state["ws"] is None:
        try:
            ws = start_ws(
                symbols,  # <- from your watchlist or session
                st.session_state["ps_api"],
                st.session_state["ui_queue"],
                st.session_state["_ws_stop_event"]
            )
            st.session_state["ws"] = ws
            st.success(f"📡 WebSocket started with {len(symbols)} symbols")
        except Exception as e:
            st.error(f"❌ WebSocket start failed: {e}")

    # --- Poll queue events ---
    while not st.session_state["ui_queue"].empty():
        try:
            event, payload = st.session_state["ui_queue"].get_nowait()
        except queue.Empty:
            break

        if event == "tp_loaded":
            df = payload
            st.session_state["ohlc_x"] = list(df.index)
            st.session_state["ohlc_o"] = list(df["open"])
            st.session_state["ohlc_h"] = list(df["high"])
            st.session_state["ohlc_l"] = list(df["low"])
            st.session_state["ohlc_c"] = list(df["close"])
            st.session_state["last_tp_dt"] = (
                st.session_state["ohlc_x"][-1] if st.session_state["ohlc_x"] else None
            )
            st.success("📥 TPSeries loaded into UI.")

        elif event == "tick":
            st.write("📩 Tick:", payload)

        elif event == "heartbeat":
            st.caption(f"💓 WS Heartbeat @ {payload}")

        elif event == "order_resp":
            st.write(f"📤 Order response — {payload.get('symbol')}: {payload.get('response')}")

        elif event == "tick_candle_update":
            sym = payload.get("symbol")
            df = payload.get("candles")
            sig = payload.get("signal")
            st.write(f"🔔 Live candle for {sym} — last signal: {sig}")
            try:
                st.dataframe(df.tail(10))
            except Exception:
                st.write(df.tail(10).to_dict())

    # --- Auto Trader Control ---
    st.subheader("🤖 Auto Trader Control")

    if "auto_trader_flag" not in st.session_state:
        st.session_state["auto_trader_flag"] = {"running": False}

    def start_auto_trader_thread(symbols, all_wls_copy, running_flag, strategy_settings, ps_api, ui_queue):
        """Thread-safe Auto Trader runner."""
        try:
            from batch_screener import main as batch_main
        except Exception as e:
            log("❌ Could not import batch_screener:", e)
            running_flag["running"] = False
            return

        log("⚡ Auto Trader thread starting with settings:", strategy_settings)
        log("⚡ Symbols to trade:", symbols)
        running_flag["running"] = True
        while running_flag["running"]:
            try:
                log("⚡ Running Auto Trader batch...")
                order_responses = batch_main(
                    ps_api=ps_api,
                    settings=strategy_settings,
                    symbols=symbols,
                    place_orders=True
                )
                log("⚡ Batch order_responses:", order_responses)
                if isinstance(order_responses, (list, tuple)):
                    for resp in order_responses:
                        log("📤 Auto Trader Order Response:", resp)
                        try:
                            ui_queue.put(("order_resp", resp))
                        except Exception:
                            pass
                else:
                    log("ℹ️ batch_main returned non-list order_responses:", order_responses)
            except Exception as e:
                log("❌ Auto Trader error:", e)

            # wait 5 min before next run
            for _ in range(300):
                if not running_flag["running"]:
                    log("🛑 Auto Trader stopped loop.")
                    return
                time.sleep(1)

    # Start button
    if st.button("🚀 Start Auto Trader"):
        if "ps_api" in st.session_state and "all_watchlists" in st.session_state:
            ps_api = st.session_state["ps_api"]
            all_wls_copy = st.session_state["all_watchlists"].copy()

            strategy_settings = (
                st.session_state.get("strategy_settings")
                or st.session_state.get("trm_settings")
            )
            if not strategy_settings:
                st.error("❌ Strategy settings not found! Configure TRM settings before starting Auto Trader.")
                st.stop()

            st.session_state["strategy_settings"] = strategy_settings
            symbols_with_tokens = []
            for wl in all_wls_copy:
                wl_data = ps_api.get_watchlist(wl)
                if wl_data.get("stat") == "Ok":
                    for s in wl_data["values"]:
                        token = s.get("token", "")
                        if token:
                            symbols_with_tokens.append({
                                "tsym": s["tsym"],
                                "exch": s["exch"],
                                "token": token
                            })

            if symbols_with_tokens:
                st.session_state["auto_trader_flag"]["running"] = True
                threading.Thread(
                    target=start_auto_trader_thread,
                    args=(symbols_with_tokens, all_wls_copy,
                          st.session_state["auto_trader_flag"],
                          strategy_settings, ps_api, st.session_state["ui_queue"]),
                    daemon=True
                ).start()
                st.success(f"✅ Auto Trader started with {len(symbols_with_tokens)} symbols from {len(all_wls_copy)} watchlists")
            else:
                st.warning("⚠️ All watchlists empty or missing tokens.")
        else:
            st.warning("⚠️ Please login first and load watchlists.")

    # Stop button
    if st.button("🛑 Stop Auto Trader"):
        st.session_state["auto_trader_flag"]["running"] = False
        st.warning("⏹️ Auto Trader stopped.")

# 🔹 Strategy Hook Registration
def on_new_candle(symbol, df):
    try:
        import streamlit as st
        from tkp_trm_chart import calc_tkp_trm

        # ✅ Fetch strategy settings from session_state
        settings = st.session_state.get("strategy_settings")
        if not settings:
            raise ValueError("❌ Strategy settings missing! Dashboard pe configure karo.")

        # ✅ Calculate TRM signals
        df_processed = calc_tkp_trm(df.copy(), settings)
        latest_signal = df_processed["trm_signal"].iloc[-1]
        print(f"📊 [{symbol}] Latest Signal → {latest_signal}")

        # ✅ Push update to UI queue if exists
        ui_queue = st.session_state.get("ui_queue")
        if ui_queue:
            ui_queue.put((
                "tick_candle_update",
                {"symbol": symbol, "candles": df_processed, "signal": latest_signal}
            ))

        # ✅ Optional Auto Order placement
        if st.session_state.get("auto_trade_enabled") and "ps_api" in st.session_state:
            ps_api = st.session_state["ps_api"]
            if latest_signal == "Buy":
                ps_api.place_order(symbol, "BUY")
            elif latest_signal == "Sell":
                ps_api.place_order(symbol, "SELL")

    except Exception as e:
        print(f"⚠️ Strategy error for {symbol}: {e}")


# Register the hook with ps_api
if "ps_api" in st.session_state:
    st.session_state["ps_api"].on_new_candle = on_new_candle


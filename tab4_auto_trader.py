# tab4_auto_trader.py
import streamlit as st
import pandas as pd
import threading
import time
import queue
from tkp_trm_chart import load_trm_settings_from_file
from dashboard_logic import save_qty_map, load_qty_map
import json

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

    q1 = st.number_input("Q1 (170-200)", min_value=1, value=current_map.get("Q1", 10), key="q1_input")
    q2 = st.number_input("Q2 (201-400)", min_value=1, value=current_map.get("Q2", 20), key="q2_input")
    q3 = st.number_input("Q3 (401-600)", min_value=1, value=current_map.get("Q3", 30), key="q3_input")
    q4 = st.number_input("Q4 (601-800)", min_value=1, value=current_map.get("Q4", 40), key="q4_input")
    q5 = st.number_input("Q5 (801-1000)", min_value=1, value=current_map.get("Q5", 50), key="q5_input")
    q6 = st.number_input("Q6 (Above 1000)", min_value=1, value=current_map.get("Q6", 60), key="q6_input")

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
    if "ui_queue" not in st.session_state:
        # use a simple in-memory queue object
        st.session_state["ui_queue"] = queue.Queue()

    # Drain ui_queue messages (non-blocking)
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
            st.session_state["last_tp_dt"] = st.session_state["ohlc_x"][-1] if st.session_state["ohlc_x"] else None
            st.success("📥 TPSeries loaded into UI.")

        elif event == "ws_started":
            st.session_state["symbols_for_ws"] = payload.get("symbols")
            st.session_state["ws_started"] = True
            st.success(f"📡 WebSocket started for {payload.get('symbols')} symbols")

        elif event == "tick":
            tick = payload
            # display minimal tick info
            st.write("📩 Tick:", tick)

        elif event == "order_resp":
            # show order responses in UI
            sym = payload.get("symbol")
            resp = payload.get("response")
            st.write(f"📤 Order response — {sym}: {resp}")

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

    # Local running flag for thread (thread-safe)
    if "auto_trader_flag" not in st.session_state:
        st.session_state["auto_trader_flag"] = {"running": False}

    # Define the thread target
    def start_auto_trader_thread(symbols, ps_api, all_wls_copy, running_flag, strategy_settings):
        """
        Wrapper thread that calls batch_screener.main with provided settings.
        We import inside the function to avoid circular imports on module load.
        """
        try:
            from batch_screener import main as batch_main
        except Exception as e:
            log("❌ Could not import batch_screener.main in thread:", e)
            running_flag["running"] = False
            return

        import argparse

        args = argparse.Namespace(
            watchlists=",".join([str(w) for w in all_wls_copy]),
            all_watchlists=False,
            interval="5",
            output=None,
            max_calls_per_min=15,
            delay_between_calls=0.25,
            place_orders=True
        )

        log("✅ Auto Trader thread started with settings:", strategy_settings)

        running_flag["running"] = True
        while running_flag["running"]:
            try:
                log("⚡ Running Auto Trader batch...")
                order_responses = batch_main(args, ps_api=ps_api, settings=strategy_settings)
                if isinstance(order_responses, (list, tuple)):
                    for resp in order_responses:
                        log("📤 Auto Trader Order Response:", resp)
                        # push to UI queue for main thread to show
                        if "ui_queue" in st.session_state:
                            try:
                                st.session_state["ui_queue"].put(("order_resp", resp))
                            except Exception:
                                pass
                else:
                    log("ℹ️ batch_main returned non-list order_responses:", order_responses)
            except Exception as e:
                log("❌ Auto Trader error:", e)

            # wait 5 minutes before next run (but allow fast stop)
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

            # ⚡ copy strategy settings here (dashboard se)
            # Respect the flags: require_session_settings / allow_file_fallback
            settings_from_session = st.session_state.get("strategy_settings")
            settings = None
            if settings_from_session:
                settings = dict(settings_from_session)
            else:
                if allow_file_fallback and not require_session_settings:
                    # File fallback allowed
                    try:
                        settings = load_trm_settings_from_file()
                    except Exception as e:
                        settings = None

            if not settings:
                st.error("❌ Strategy settings not found in session_state and file fallback not allowed. Configure settings in dashboard before starting Auto Trader.")
            else:
                # Get unique symbols from all watchlists
                symbols = []
                for wl in all_wls_copy:
                    wl_data = ps_api.get_watchlist(wl)
                    if wl_data.get("stat") == "Ok":
                        df = pd.DataFrame(wl_data["values"])
                        if not df.empty:
                            symbols.extend(df["tsym"].tolist())
                symbols = list(set(symbols))

                if symbols:
                    st.session_state["auto_trader_flag"]["running"] = True
                    threading.Thread(
                        target=start_auto_trader_thread,
                        args=(symbols, ps_api, all_wls_copy, st.session_state["auto_trader_flag"], settings),
                        daemon=True
                    ).start()

                    st.success(f"✅ Auto Trader started with {len(symbols)} symbols from {len(all_wls_copy)} watchlists")
                else:
                    st.warning("⚠️ All watchlists are empty, cannot start Auto Trader.")
        else:
            st.warning("⚠️ Please login first and load watchlists.")

    # Stop button
    if st.button("🛑 Stop Auto Trader"):
        st.session_state["auto_trader_flag"]["running"] = False
        st.warning("⏹️ Auto Trader stopped.")

# 🔹 Strategy Hook Registration
def on_new_candle(symbol, df):
    try:
        from tkp_trm_chart import calc_tkp_trm
        settings = st.session_state.get("strategy_settings")

        if not settings:
            raise ValueError("❌ Strategy settings missing! Dashboard pe configure karo.")

        df = calc_tkp_trm(df.copy(), settings)
        latest_signal = df["trm_signal"].iloc[-1]
        print(f"📊 [{symbol}] Latest Signal → {latest_signal}")

        # UI queue update
        if "ui_queue" in st.session_state:
            st.session_state["ui_queue"].put((
                "tick_candle_update",
                {"symbol": symbol, "candles": df, "signal": latest_signal}
            ))

        # Optional Auto Order
        if st.session_state.get("auto_trade_enabled"):
            if latest_signal == "Buy":
                st.session_state["ps_api"].place_order(symbol, "BUY")
            elif latest_signal == "Sell":
                st.session_state["ps_api"].place_order(symbol, "SELL")

    except Exception as e:
        print(f"⚠️ Strategy error for {symbol}: {e}")


# Register the hook with ps_api
if "ps_api" in st.session_state:
    st.session_state["ps_api"].on_new_candle = on_new_candle



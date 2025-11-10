# tab4_auto_trader.py
import streamlit as st
import pandas as pd
import threading
import time
import queue
from datetime import datetime
from tkp_trm_chart import load_trm_settings_from_file
from dashboard_logic import save_qty_map, load_qty_map
import json

# 🔹 Global queue for thread -> UI communication
# ui_queue = queue.Queue()
# AUTO_TRADE_FLAG = False
# strategy_settings_copy = None


# Helper: safe print (so it shows in server logs)
def log(*args, **kwargs):
    print(*args, **kwargs)


# 🔹 WebSocket starter (define here, no import needed)
def start_ws(symbols, ps_api, ui_queue, stop_event):
    # ❌ Do NOT connect WebSocket here
    # We just store parameters and wait for user to start Auto Trader.
    ui_queue.put(("info", "WS Ready (but not started)"), block=False)
    return None    
    def on_tick_callback(tick):
        try:
            ui_queue.put(("tick", tick), block=False)
        except Exception:
            pass

    try:
        ws = ps_api.connect_websocket(symbols, on_tick=on_tick_callback, tick_file="ticks_tab5.log")

        # ✅ Heartbeat thread
        def heartbeat(ws, stop_event):
            while not stop_event.is_set():
                try:
                    ws.send("ping")
                    hb = datetime.now().strftime("%H:%M:%S")
                    ui_queue.put(("heartbeat", hb), block=False)
                except Exception:
                    break
                time.sleep(20)

        threading.Thread(target=heartbeat, args=(ws, stop_event), daemon=True).start()
        return ws

    except Exception as e:
        ui_queue.put(("ws_error", str(e)), block=False)
        return None

def render_tab4(require_session_settings=False, allow_file_fallback=True):
    """
    Render the Indicator Settings / Auto Trader control UI (Tab 4).
    """

    # ✅ SAFE LOGIN CHECK (Runs only when Tab 4 UI is displayed)
    if not st.session_state.get("logged_in", False):
        st.info("🔐 Please login first to use Auto Trader settings.")
        return

    # ✅ Load TRM settings once
    if "trm_settings" not in st.session_state or not st.session_state["trm_settings"]:
        st.session_state["trm_settings"] = load_trm_settings_from_file()

    # ✅ Load Qty Map once
    if "qty_map" not in st.session_state or not st.session_state["qty_map"]:
        st.session_state["qty_map"] = load_qty_map()

    # ✅ Show subheader only once per session
    if "trm_qty_subheader_shown" not in st.session_state:
        st.subheader("📦 Position Quantity Mapping")
        st.session_state["trm_qty_subheader_shown"] = True

    # ✅ Load qty_map from session_state (auto-loaded above)
    current_map = st.session_state.get("qty_map", {})

    # --- 20 number inputs for 20 price ranges ---
    q1  = st.number_input("Q1 (1-100)", min_value=1, value=current_map.get("Q1", 1), key="q1_input")
    q2  = st.number_input("Q2 (101-150)", min_value=1, value=current_map.get("Q2", 1), key="q2_input")
    q3  = st.number_input("Q3 (151-200)", min_value=1, value=current_map.get("Q3", 1), key="q3_input")
    q4  = st.number_input("Q4 (201-250)", min_value=1, value=current_map.get("Q4", 1), key="q4_input")
    q5  = st.number_input("Q5 (251-300)", min_value=1, value=current_map.get("Q5", 1), key="q5_input")
    q6  = st.number_input("Q6 (301-350)", min_value=1, value=current_map.get("Q6", 1), key="q6_input")
    q7  = st.number_input("Q7 (351-400)", min_value=1, value=current_map.get("Q7", 1), key="q7_input")
    q8  = st.number_input("Q8 (401-450)", min_value=1, value=current_map.get("Q8", 1), key="q8_input")
    q9  = st.number_input("Q9 (451-500)", min_value=1, value=current_map.get("Q9", 1), key="q9_input")
    q10 = st.number_input("Q10 (501-550)", min_value=1, value=current_map.get("Q10", 1), key="q10_input")
    q11 = st.number_input("Q11 (551-600)", min_value=1, value=current_map.get("Q11", 1), key="q11_input")
    q12 = st.number_input("Q12 (601-650)", min_value=1, value=current_map.get("Q12", 1), key="q12_input")
    q13 = st.number_input("Q13 (651-700)", min_value=1, value=current_map.get("Q13", 1), key="q13_input")
    q14 = st.number_input("Q14 (701-750)", min_value=1, value=current_map.get("Q14", 1), key="q14_input")
    q15 = st.number_input("Q15 (751-800)", min_value=1, value=current_map.get("Q15", 1), key="q15_input")
    q16 = st.number_input("Q16 (801-850)", min_value=1, value=current_map.get("Q16", 1), key="q16_input")
    q17 = st.number_input("Q17 (851-900)", min_value=1, value=current_map.get("Q17", 1), key="q17_input")
    q18 = st.number_input("Q18 (901-950)", min_value=1, value=current_map.get("Q18", 1), key="q18_input")
    q19 = st.number_input("Q19 (951-1000)", min_value=1, value=current_map.get("Q19", 1), key="q19_input")
    q20 = st.number_input("Q20 (Above 1000)", min_value=1, value=current_map.get("Q20", 1), key="q20_input")

    # --- Build qty_map dict ---
    qty_map = {
        "Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4, "Q5": q5,
        "Q6": q6, "Q7": q7, "Q8": q8, "Q9": q9, "Q10": q10,
        "Q11": q11, "Q12": q12, "Q13": q13, "Q14": q14, "Q15": q15,
        "Q16": q16, "Q17": q17, "Q18": q18, "Q19": q19, "Q20": q20
    }

    # ✅ Save button
    if st.button("💾 Save Quantity Mapping"):
        try:
            save_qty_map(qty_map)
            st.session_state["qty_map"] = qty_map  # ✅ Update in session_state
            st.success("✅ Quantity mapping saved & loaded successfully.")
        except Exception as e:
            st.error(f"❌ Could not save qty map: {e}")

    st.write("📌 Current Quantity Mapping:", qty_map)
  

    # --- Queue & WS Init ---
    if "ui_queue" not in st.session_state:
        st.session_state["ui_queue"] = queue.Queue()

    if "_ws_stop_event" not in st.session_state:
        st.session_state["_ws_stop_event"] = threading.Event()

    # ✅ WebSocket will now start only when Auto Trader starts, not before
    st.warning("⚠️ WebSocket will start only when Auto Trader is started.")

    show_ticks = st.checkbox("Show raw ticks (debug)", value=False)

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
            if show_ticks:  # ✅ ticks only when debugging
                tsym = st.session_state["symbols_map"].get(
                    payload.get("symbol"), payload.get("symbol")
                )
                st.write(f"📩 Tick: {tsym} → {payload}")
           
        elif event == "heartbeat":
            st.caption(f"💓 WS Heartbeat @ {payload}")

        elif event == "order_resp":
            st.write(f"📤 Order response — {payload.get('symbol')}: {payload.get('response')}")

        elif event == "tick_candle_update":
            sym = payload.get("symbol")
            tsym = st.session_state["symbols_map"].get(sym, sym)  # ✅ readable name
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

    import asyncio

    def start_auto_trader_thread(symbols, all_wls_copy, running_flag, strategy_settings, ps_api, ui_queue):
        """Thread-safe Auto Trader runner using asyncio.to_thread for blocking batch_main"""
        async def auto_loop():
            running_flag["running"] = True
            while running_flag["running"]:
                try:
                    # run blocking batch_main in a thread pool
                    res = await asyncio.to_thread(batch_main, ps_api, None, strategy_settings, symbols, True)
                    # push responses to UI queue
                    try:
                        for r in res.get("orders", []) if isinstance(res, dict) else []:
                            ui_queue.put(("order_resp", r))
                    except Exception:
                        pass
                except Exception as e:
                    print("❌ Auto Trader error:", e)
                # wait between batches
                await asyncio.sleep(3)
            print("🛑 Auto Trader loop exited")

        # Run the async loop in a separate daemon thread
        def runner():
            asyncio.run(auto_loop())

        threading.Thread(target=runner, daemon=True).start()


    # Start button
    # Start button
    if st.button("🚀 Start Auto Trader"):

        try:
            # ✅ Start WebSocket ONLY NOW (no auto connect on reruns)
            from prostocks_connector import ProStocksAPI

            ws = st.session_state["ps_api"].connect_websocket(
                st.session_state["symbols_for_ws"],   # list of tokens
                on_tick=None                          # tick callback disable until strategy loop
            )

            st.session_state["ws"] = ws
            st.session_state["ps_api"].is_ws_connected = True  # ✅ Prevent re-connect attempts

            st.success(f"📡 WebSocket Started for {len(st.session_state['symbols_for_ws'])} symbol(s)")

        except Exception as e:
            st.error(f"❌ WS Start Error: {e}")
            st.stop()

        # --- Continue Auto Trader logic below (unchanged) ---
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
# if "ps_api" in st.session_state and st.session_state["ps_api"] is not None:
#     try:
#        st.session_state["ps_api"].on_new_candle = on_new_candle
#    except Exception as e:
#        st.warning(f"⚠️ Could not set on_new_candle: {e}")









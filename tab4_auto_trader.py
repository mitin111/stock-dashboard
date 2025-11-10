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

# Global queue for thread -> UI communication
# ui_queue = queue.Queue()
# AUTO_TRADE_FLAG = False
# strategy_settings_copy = None


# Helper: safe print (so it shows in server logs)
def log(*args, **kwargs):
<press normal space once><press normal space once>print(*args, **kwargs)


# WebSocket starter (define here, no import needed)
def start_ws(symbols, ps_api, ui_queue, stop_event):
<press normal space once><press normal space once>"""
<press normal space once><press normal space once>This version does NOT auto-start WebSocket.
<press normal space once><press normal space once>It only stores params and waits for Auto Trader button.
<press normal space once><press normal space once>"""
<press normal space once><press normal space once>ui_queue.put(("info", "WS Ready (but not started)"), block=False)
<press normal space once><press normal space once>return None


def on_tick_callback(tick):
<press normal space once><press normal space once>try:
<press normal space once><press normal space once><press normal space once><press normal space once>ui_queue.put(("tick", tick), block=False)
<press normal space once><press normal space once>except Exception:
<press normal space once><press normal space once><press normal space once><press normal space once>pass


def start_ws(symbols, ps_api, ui_queue, stop_event):
<press normal space once><press normal space once>try:
<press normal space once><press normal space once><press normal space once><press normal space once>ws = ps_api.connect_websocket(symbols, on_tick=on_tick_callback, tick_file="ticks_tab5.log")

<press normal space once><press normal space once><press normal space once><press normal space once># Heartbeat thread
<press normal space once><press normal space once><press normal space once><press normal space once>def heartbeat(ws, stop_event):
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>while not stop_event.is_set():
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>try:
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>ws.send("ping")
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>hb = datetime.now().strftime("%H:%M:%S")
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>ui_queue.put(("heartbeat", hb), block=False)
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>except Exception:
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>break
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>time.sleep(20)

<press normal space once><press normal space once><press normal space once><press normal space once>threading.Thread(target=heartbeat, args=(ws, stop_event), daemon=True).start()
<press normal space once><press normal space once><press normal space once><press normal space once>return ws

<press normal space once><press normal space once>except Exception as e:
<press normal space once><press normal space once><press normal space once><press normal space once>ui_queue.put(("ws_error", str(e)), block=False)
<press normal space once><press normal space once><press normal space once><press normal space once>return None


def render_tab4(require_session_settings=False, allow_file_fallback=True):
<press normal space once>"""
<press normal space once>Render the Indicator Settings / Auto Trader control UI (Tab 4).
<press normal space once>"""

<press normal space once># SAFE LOGIN CHECK (Runs only when Tab 4 UI is displayed)
<press normal space once>if not st.session_state.get("logged_in", False):
<press normal space once><press normal space once>st.info(" Please login first to use Auto Trader settings.")
<press normal space once><press normal space once>return

<press normal space once># Load TRM settings once
<press normal space once>if "trm_settings" not in st.session_state or not st.session_state["trm_settings"]:
<press normal space once><press normal space once>st.session_state["trm_settings"] = load_trm_settings_from_file()

<press normal space once># Load Qty Map once
<press normal space once>if "qty_map" not in st.session_state or not st.session_state["qty_map"]:
<press normal space once><press normal space once>st.session_state["qty_map"] = load_qty_map()

<press normal space once># Show subheader only once per session
<press normal space once>if "trm_qty_subheader_shown" not in st.session_state:
<press normal space once><press normal space once>st.subheader(" Position Quantity Mapping")
<press normal space once><press normal space once>st.session_state["trm_qty_subheader_shown"] = True

<press normal space once># Load qty_map from session_state (auto-loaded above)
<press normal space once>current_map = st.session_state.get("qty_map", {})

<press normal space once># --- 20 number inputs for 20 price ranges ---
<press normal space once>q1 = st.number_input("Q1 (1-100)", min_value=1, value=current_map.get("Q1", 1), key="q1_input")
<press normal space once>q2 = st.number_input("Q2 (101-150)", min_value=1, value=current_map.get("Q2", 1), key="q2_input")
<press normal space once>q3 = st.number_input("Q3 (151-200)", min_value=1, value=current_map.get("Q3", 1), key="q3_input")
<press normal space once>q4 = st.number_input("Q4 (201-250)", min_value=1, value=current_map.get("Q4", 1), key="q4_input")
<press normal space once>q5 = st.number_input("Q5 (251-300)", min_value=1, value=current_map.get("Q5", 1), key="q5_input")
<press normal space once>q6 = st.number_input("Q6 (301-350)", min_value=1, value=current_map.get("Q6", 1), key="q6_input")
<press normal space once>q7 = st.number_input("Q7 (351-400)", min_value=1, value=current_map.get("Q7", 1), key="q7_input")
<press normal space once>q8 = st.number_input("Q8 (401-450)", min_value=1, value=current_map.get("Q8", 1), key="q8_input")
<press normal space once>q9 = st.number_input("Q9 (451-500)", min_value=1, value=current_map.get("Q9", 1), key="q9_input")
<press normal space once>q10 = st.number_input("Q10 (501-550)", min_value=1, value=current_map.get("Q10", 1), key="q10_input")
<press normal space once>q11 = st.number_input("Q11 (551-600)", min_value=1, value=current_map.get("Q11", 1), key="q11_input")
<press normal space once>q12 = st.number_input("Q12 (601-650)", min_value=1, value=current_map.get("Q12", 1), key="q12_input")
<press normal space once>q13 = st.number_input("Q13 (651-700)", min_value=1, value=current_map.get("Q13", 1), key="q13_input")
<press normal space once>q14 = st.number_input("Q14 (701-750)", min_value=1, value=current_map.get("Q14", 1), key="q14_input")
<press normal space once>q15 = st.number_input("Q15 (751-800)", min_value=1, value=current_map.get("Q15", 1), key="q15_input")
<press normal space once>q16 = st.number_input("Q16 (801-850)", min_value=1, value=current_map.get("Q16", 1), key="q16_input")
<press normal space once>q17 = st.number_input("Q17 (851-900)", min_value=1, value=current_map.get("Q17", 1), key="q17_input")
<press normal space once>q18 = st.number_input("Q18 (901-950)", min_value=1, value=current_map.get("Q18", 1), key="q18_input")
<press normal space once>q19 = st.number_input("Q19 (951-1000)", min_value=1, value=current_map.get("Q19", 1), key="q19_input")
<press normal space once>q20 = st.number_input("Q20 (Above 1000)", min_value=1, value=current_map.get("Q20", 1), key="q20_input")

<press normal space once># --- Build qty_map dict ---
<press normal space once>qty_map = {
<press normal space once><press normal space once>"Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4, "Q5": q5,
<press normal space once><press normal space once>"Q6": q6, "Q7": q7, "Q8": q8, "Q9": q9, "Q10": q10,
<press normal space once><press normal space once>"Q11": q11, "Q12": q12, "Q13": q13, "Q14": q14, "Q15": q15,
<press normal space once><press normal space once>"Q16": q16, "Q17": q17, "Q18": q18, "Q19": q19, "Q20": q20
<press normal space once>}

<press normal space once># Save button
<press normal space once>if st.button(" Save Quantity Mapping"):
<press normal space once><press normal space once>try:
<press normal space once><press normal space once><press normal space once>save_qty_map(qty_map)
<press normal space once><press normal space once><press normal space once>st.session_state["qty_map"] = qty_map # Update in session_state
<press normal space once><press normal space once><press normal space once>st.success(" Quantity mapping saved & loaded successfully.")
<press normal space once><press normal space once>except Exception as e:
<press normal space once><press normal space once><press normal space once>st.error(f" Could not save qty map: {e}")

<press normal space once>st.write(" Current Quantity Mapping:", qty_map)
 

<press normal space once># --- Queue & WS Init ---
<press normal space once>if "ui_queue" not in st.session_state:
<press normal space once><press normal space once>st.session_state["ui_queue"] = queue.Queue()

<press normal space once>if "_ws_stop_event" not in st.session_state:
<press normal space once><press normal space once>st.session_state["_ws_stop_event"] = threading.Event()

<press normal space once># WebSocket will now start only when Auto Trader starts, not before
<press normal space once>st.warning(" WebSocket will start only when Auto Trader is started.")

<press normal space once>show_ticks = st.checkbox("Show raw ticks (debug)", value=False)

<press normal space once># --- Poll queue events ---
<press normal space once>while not st.session_state["ui_queue"].empty():
<press normal space once><press normal space once>try:
<press normal space once><press normal space once><press normal space once>event, payload = st.session_state["ui_queue"].get_nowait()
<press normal space once><press normal space once>except queue.Empty:
<press normal space once><press normal space once><press normal space once>break

<press normal space once><press normal space once>if event == "tp_loaded":
<press normal space once><press normal space once><press normal space once>df = payload
<press normal space once><press normal space once><press normal space once>st.session_state["ohlc_x"] = list(df.index)
<press normal space once><press normal space once><press normal space once>st.session_state["ohlc_o"] = list(df["open"])
<press normal space once><press normal space once><press normal space once>st.session_state["ohlc_h"] = list(df["high"])
<press normal space once><press normal space once><press normal space once>st.session_state["ohlc_l"] = list(df["low"])
<press normal space once><press normal space once><press normal space once>st.session_state["ohlc_c"] = list(df["close"])
<press normal space once><press normal space once><press normal space once>st.session_state["last_tp_dt"] = (
<press normal space once><press normal space once><press normal space once><press normal space once>st.session_state["ohlc_x"][-1] if st.session_state["ohlc_x"] else None
<press normal space once><press normal space once><press normal space once>)
<press normal space once><press normal space once><press normal space once>st.success(" TPSeries loaded into UI.")

<press normal space once><press normal space once>elif event == "tick":
<press normal space once><press normal space once><press normal space once>if show_ticks: # ticks only when debugging
<press normal space once><press normal space once><press normal space once><press normal space once>tsym = st.session_state["symbols_map"].get(
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>payload.get("symbol"), payload.get("symbol")
<press normal space once><press normal space once><press normal space once><press normal space once>)
<press normal space once><press normal space once><press normal space once><press normal space once>st.write(f" Tick: {tsym} → {payload}")
<press normal space once><press normal space once> 
<press normal space once><press normal space once>elif event == "heartbeat":
<press normal space once><press normal space once><press normal space once>st.caption(f" WS Heartbeat @ {payload}")

<press normal space once><press normal space once>elif event == "order_resp":
<press normal space once><press normal space once><press normal space once>st.write(f" Order response — {payload.get('symbol')}: {payload.get('response')}")

<press normal space once><press normal space once>elif event == "tick_candle_update":
<press normal space once><press normal space once><press normal space once>sym = payload.get("symbol")
<press normal space once><press normal space once><press normal space once>tsym = st.session_state["symbols_map"].get(sym, sym) # readable name
<press normal space once><press normal space once><press normal space once>df = payload.get("candles")
<press normal space once><press normal space once><press normal space once>sig = payload.get("signal")
<press normal space once><press normal space once><press normal space once>st.write(f" Live candle for {sym} — last signal: {sig}")
<press normal space once><press normal space once><press normal space once>try:
<press normal space once><press normal space once><press normal space once><press normal space once>st.dataframe(df.tail(10))
<press normal space once><press normal space once><press normal space once>except Exception:
<press normal space once><press normal space once><press normal space once><press normal space once>st.write(df.tail(10).to_dict())

<press normal space once># --- Auto Trader Control ---
<press normal space once>st.subheader(" Auto Trader Control")

<press normal space once>if "auto_trader_flag" not in st.session_state:
<press normal space once><press normal space once>st.session_state["auto_trader_flag"] = {"running": False}

<press normal space once>import asyncio

<press normal space once>def start_auto_trader_thread(symbols, all_wls_copy, running_flag, strategy_settings, ps_api, ui_queue):
<press normal space once><press normal space once>"""Thread-safe Auto Trader runner using asyncio.to_thread for blocking batch_main"""
<press normal space once><press normal space once>async def auto_loop():
<press normal space once><press normal space once><press normal space once>running_flag["running"] = True
<press normal space once><press normal space once><press normal space once>while running_flag["running"]:
<press normal space once><press normal space once><press normal space once><press normal space once>try:
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once># run blocking batch_main in a thread pool
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>res = await asyncio.to_thread(batch_main, ps_api, None, strategy_settings, symbols, True)
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once># push responses to UI queue
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>try:
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>for r in res.get("orders", []) if isinstance(res, dict) else []:
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>ui_queue.put(("order_resp", r))
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>except Exception:
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>pass
<press normal space once><press normal space once><press normal space once><press normal space once>except Exception as e:
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>print(" Auto Trader error:", e)
<press normal space once><press normal space once><press normal space once><press normal space once># wait between batches
<press normal space once><press normal space once><press normal space once><press normal space once>await asyncio.sleep(3)
<press normal space once><press normal space once><press normal space once>print(" Auto Trader loop exited")

<press normal space once><press normal space once># Run the async loop in a separate daemon thread
<press normal space once><press normal space once>def runner():
<press normal space once><press normal space once><press normal space once>asyncio.run(auto_loop())

<press normal space once><press normal space once>threading.Thread(target=runner, daemon=True).start()


<press normal space once># Start button
<press normal space once># Start button
<press normal space once>if st.button(" Start Auto Trader"):

<press normal space once><press normal space once>try:
<press normal space once><press normal space once><press normal space once># Start WebSocket ONLY NOW (no auto connect on reruns)
<press normal space once><press normal space once><press normal space once>from prostocks_connector import ProStocksAPI

<press normal space once><press normal space once><press normal space once>ws = st.session_state["ps_api"].connect_websocket(
<press normal space once><press normal space once><press normal space once><press normal space once>st.session_state["symbols_for_ws"],<press normal space once># list of tokens
<press normal space once><press normal space once><press normal space once><press normal space once>on_tick=None<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once> # tick callback disable until strategy loop
<press normal space once><press normal space once><press normal space once>)

<press normal space once><press normal space once><press normal space once>st.session_state["ws"] = ws
<press normal space once><press normal space once><press normal space once>st.session_state["ps_api"].is_ws_connected = True # Prevent re-connect attempts

<press normal space once><press normal space once><press normal space once>st.success(f" WebSocket Started for {len(st.session_state['symbols_for_ws'])} symbol(s)")

<press normal space once><press normal space once>except Exception as e:
<press normal space once><press normal space once><press normal space once>st.error(f" WS Start Error: {e}")
<press normal space once><press normal space once><press normal space once>st.stop()

<press normal space once><press normal space once># --- Continue Auto Trader logic below (unchanged) ---
<press normal space once><press normal space once>if "ps_api" in st.session_state and "all_watchlists" in st.session_state:
<press normal space once><press normal space once><press normal space once>ps_api = st.session_state["ps_api"]
<press normal space once><press normal space once><press normal space once>all_wls_copy = st.session_state["all_watchlists"].copy()

<press normal space once><press normal space once><press normal space once>strategy_settings = (
<press normal space once><press normal space once><press normal space once><press normal space once>st.session_state.get("strategy_settings")
<press normal space once><press normal space once><press normal space once><press normal space once>or st.session_state.get("trm_settings")
<press normal space once><press normal space once><press normal space once>)
<press normal space once><press normal space once><press normal space once>if not strategy_settings:
<press normal space once><press normal space once><press normal space once><press normal space once>st.error(" Strategy settings not found! Configure TRM settings before starting Auto Trader.")
<press normal space once><press normal space once><press normal space once><press normal space once>st.stop()


<press normal space once><press normal space once><press normal space once>st.session_state["strategy_settings"] = strategy_settings
<press normal space once><press normal space once><press normal space once>symbols_with_tokens = []
<press normal space once><press normal space once><press normal space once>for wl in all_wls_copy:
<press normal space once><press normal space once><press normal space once><press normal space once>wl_data = ps_api.get_watchlist(wl)
<press normal space once><press normal space once><press normal space once><press normal space once>if wl_data.get("stat") == "Ok":
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>for s in wl_data["values"]:
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>token = s.get("token", "")
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>if token:
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>symbols_with_tokens.append({
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>"tsym": s["tsym"],
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>"exch": s["exch"],
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>"token": token
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>})

<press normal space once><press normal space once><press normal space once>if symbols_with_tokens:
<press normal space once><press normal space once><press normal space once><press normal space once>st.session_state["auto_trader_flag"]["running"] = True
<press normal space once><press normal space once><press normal space once><press normal space once>threading.Thread(
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>target=start_auto_trader_thread,
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>args=(symbols_with_tokens, all_wls_copy,
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once> st.session_state["auto_trader_flag"],
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once><press normal space once> strategy_settings, ps_api, st.session_state["ui_queue"]),
<press normal space once><press normal space once><press normal space once><press normal space once><press normal space once>daemon=True
<press normal space once><press normal space once><press normal space once><press normal space once>).start()
<press normal space once><press normal space once><press normal space once><press normal space once>st.success(f" Auto Trader started with {len(symbols_with_tokens)} symbols from {len(all_wls_copy)} watchlists")
<press normal space once><press normal space once><press normal space once>else:
<press normal space once><press normal space once><press normal space once><press normal space once>st.warning(" All watchlists empty or missing tokens.")
<press normal space once><press normal space once>else:
<press normal space once><press normal space once><press normal space once>st.warning(" Please login first and load watchlists.")

<press normal space once># Stop button
<press normal space once>if st.button(" Stop Auto Trader"):
<press normal space once><press normal space once>st.session_state["auto_trader_flag"]["running"] = False
<press normal space once><press normal space once>st.warning(" Auto Trader stopped.")

# Strategy Hook Registration
def on_new_candle(symbol, df):
<press normal space once>try:
<press normal space once><press normal space once>import streamlit as st
<press normal space once><press normal space once>from tkp_trm_chart import calc_tkp_trm

<press normal space once><press normal space once># Fetch strategy settings from session_state
<press normal space once><press normal space once>settings = st.session_state.get("strategy_settings")
<press normal space once><press normal space once>if not settings:
<press normal space once><press normal space once><press normal space once>raise ValueError(" Strategy settings missing! Dashboard pe configure karo.")

<press normal space once><press normal space once># Calculate TRM signals
<press normal space once><press normal space once>df_processed = calc_tkp_trm(df.copy(), settings)
<press normal space once><press normal space once>latest_signal = df_processed["trm_signal"].iloc[-1]
<press normal space once><press normal space once>print(f" [{symbol}] Latest Signal → {latest_signal}")

<press normal space once><press normal space once># Push update to UI queue if exists
<press normal space once><press normal space once>ui_queue = st.session_state.get("ui_queue")
<press normal space once><press normal space once>if ui_queue:
<press normal space once><press normal space once><press normal space once>ui_queue.put((
<press normal space once><press normal space once><press normal space once><press normal space once>"tick_candle_update",
<press normal space once><press normal space once><press normal space once><press normal space once>{"symbol": symbol, "candles": df_processed, "signal": latest_signal}
<press normal space once><press normal space once><press normal space once>))

<press normal space once><press normal space once># Optional Auto Order placement
<press normal space once><press normal space once>if st.session_state.get("auto_trade_enabled") and "ps_api" in st.session_state:
<press normal space once><press normal space once><press normal space once>ps_api = st.session_state["ps_api"]
<press normal space once><press normal space once><press normal space once>if latest_signal == "Buy":
<press normal space once><press normal space once><press normal space once><press normal space once>ps_api.place_order(symbol, "BUY")
<press normal space once><press normal space once><press normal space once>elif latest_signal == "Sell":
<press normal space once><press normal space once><press normal space once><press normal space once>ps_api.place_order(symbol, "SELL")

<press normal space once>except Exception as e:
<press normal space once><press normal space once>print(f" Strategy error for {symbol}: {e}")


# Register the hook with ps_api
# if "ps_api" in st.session_state and st.session_state["ps_api"] is not None:
#<press normal space once> try:
#<press normal space once><press normal space once>st.session_state["ps_api"].on_new_candle = on_new_candle
#<press normal space once>except Exception as e:
#<press normal space once><press normal space once>st.warning(f" Could not set on_new_candle: {e}")






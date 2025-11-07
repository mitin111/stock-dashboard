# stock_dashboard_phase1.py
import streamlit as st
import pandas as pd
from prostocks_connector import ProStocksAPI
from dashboard_logic import load_settings, save_settings, load_credentials
from datetime import datetime, timedelta
import calendar
import time
import json
import requests
from urllib.parse import urlencode
from datetime import timezone
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pytz

try:
    import websocket
except:
    websocket = None
    
def check_backend_ws(url: str, timeout=5) -> bool:
    """Check if backend WebSocket server is reachable"""
    try:
        ws = websocket.create_connection(url, timeout=timeout)
        ws.close()
        return True
    except Exception as e:
        print(f"❌ WebSocket check failed: {e}")
        return False

# === Page Layout ===
st.set_page_config(page_title="Auto Intraday Trading", layout="wide")
# ✅ Add this line just after set_page_config
st.markdown('<meta name="render-health-check" content="ok">', unsafe_allow_html=True)
st.title("📈 Automated Intraday Trading System")

# === Load Settings (once) ===
if "settings_loaded" not in st.session_state:
    st.session_state.update(load_settings())
    st.session_state["settings_loaded"] = True

# === Load Credentials ===
creds = load_credentials()

# === Sidebar Login ===
with st.sidebar:
    st.header("🔐 ProStocks OTP Login")
    if st.button("📩 Send OTP"):
        temp_api = ProStocksAPI(**creds)
        success, msg = temp_api.login("")
        st.success("✅ OTP Sent") if success else st.info(f"ℹ️ {msg}")

    with st.form("LoginForm"):
        uid = st.text_input("User ID", value=creds["uid"])
        pwd = st.text_input("Password", type="password", value=creds["pwd"])
        factor2 = st.text_input("OTP from SMS/Email")
        vc = st.text_input("Vendor Code", value=creds["vc"] or uid)
        api_key = st.text_input("API Key", type="password", value=creds["api_key"])
        imei = st.text_input("MAC Address", value=creds["imei"])
        base_url = st.text_input("Base URL", value=creds["base_url"])
        apkversion = st.text_input("APK Version", value=creds["apkversion"])

        submitted = st.form_submit_button("🔐 Login")
        if submitted:
            try:
                ps_api = ProStocksAPI(
                    userid=uid, password_plain=pwd, vc=vc,
                    api_key=api_key, imei=imei,
                    base_url=base_url, apkversion=apkversion
                )
                success, msg = ps_api.login(factor2)

                if success:
                    st.session_state["ps_api"] = ps_api
                    st.session_state["logged_in"] = True   # ✅ mark login successful

                    backend_ws_url = "wss://backend-stream-1ij9.onrender.com/ws/live"
                    st.session_state["ws_backend_ok"] = True
                    st.success("✅ Login Successful")

                else:
                    st.error(f"❌ Login failed: {msg}")

            except Exception as e:
                st.error(f"❌ Exception: {e}")

if st.sidebar.button("🔓 Logout"):
    st.session_state.pop("ps_api", None)
    st.session_state["logged_in"] = False
    st.success("✅ Logged out successfully")

# === Tabs ===
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "⚙️ Trade Controls",
    "📊 Dashboard",
    "📈 Market Data",
    "📀 Indicator Settings",
    "📉 Strategy Engine"
])

# === Tab 1: Trade Controls ===
with tab1:
    st.subheader("⚙️ Step 0: Trading Control Panel")
    master = st.toggle("✅ Master Auto Buy + Sell", st.session_state.get("master_auto", True), key="master_toggle")
    auto_buy = st.toggle("▶️ Auto Buy Enabled", st.session_state.get("auto_buy", True), key="auto_buy_toggle")
    auto_sell = st.toggle("🔽 Auto Sell Enabled", st.session_state.get("auto_sell", True), key="auto_sell_toggle")

    def time_state(key, default_str):
        if key not in st.session_state:
            st.session_state[key] = datetime.strptime(default_str, "%H:%M").time()
        return st.time_input(key.replace("_", " ").title(), value=st.session_state[key], key=key)

    trading_start = time_state("trading_start", "09:15")
    trading_end = time_state("trading_end", "15:15")
    cutoff_time = time_state("cutoff_time", "14:50")
    auto_exit_time = time_state("auto_exit_time", "15:12")

    save_settings({
        "master_auto": master,
        "auto_buy": auto_buy,
        "auto_sell": auto_sell,
        "trading_start": trading_start.strftime("%H:%M"),
        "trading_end": trading_end.strftime("%H:%M"),
        "cutoff_time": cutoff_time.strftime("%H:%M"),
        "auto_exit_time": auto_exit_time.strftime("%H:%M")
    })

import numpy as np
import json

# === Tab 2: Dashboard ===
with tab2:
    st.subheader("📊 Dashboard")

    logged_in = ("ps_api" in st.session_state) and st.session_state.ps_api.is_logged_in()
    if not logged_in:
        st.info("🔐 Please login first to view Dashboard.")
    else:
        ps_api = st.session_state.ps_api
        col1, col2 = st.columns(2)

        if st.button("🔄 Refresh Order/Trade Book"):
            ps_api._order_book = ps_api.order_book()
            ps_api._trade_book = ps_api.trade_book()

        ob_placeholder = st.empty()
        tb_placeholder = st.empty()

        with col1:
            st.markdown("### 📑 Order Book")
            try:
                ob_list = ps_api._order_book if hasattr(ps_api, "_order_book") else ps_api.order_book()
                if isinstance(ob_list, dict):
                    ob_list = [ob_list]
                elif not isinstance(ob_list, list):
                    ob_list = []
                df_ob = pd.DataFrame(ob_list)
                if not df_ob.empty:
                    show_cols = ["norenordno","exch","tsym","trantype","qty","prc","prctyp","status","rejreason","avgprc","ordenttm","norentm"]
                    df_ob = df_ob.reindex(columns=show_cols, fill_value=np.nan)
                    ob_placeholder.dataframe(df_ob, use_container_width=True, height=400)
                else:
                    ob_placeholder.info("📭 No orders found.")
            except Exception as e:
                ob_placeholder.error(f"❌ Error fetching Order Book: {e}")

        with col2:
            st.markdown("### 📑 Trade Book")
            try:
                tb_list = ps_api._trade_book if hasattr(ps_api, "_trade_book") else ps_api.trade_book()
                if isinstance(tb_list, dict):
                    tb_list = [tb_list]
                elif not isinstance(tb_list, list):
                    tb_list = []
                df_tb = pd.DataFrame(tb_list)
                if not df_tb.empty:
                    show_cols = ["norenordno","exch","tsym","trantype","fillshares","avgprc","status","norentm"]
                    df_tb = df_tb.reindex(columns=show_cols, fill_value=np.nan)
                    tb_placeholder.dataframe(df_tb, use_container_width=True, height=400)
                else:
                    tb_placeholder.info("📭 No trades found.")
            except Exception as e:
                tb_placeholder.error(f"❌ Error fetching Trade Book: {e}")


# === Tab 3: Market Data ===
with tab3:
    st.subheader("📈 Live Market Table – Watchlist Viewer")

    logged_in = ("ps_api" in st.session_state) and st.session_state.ps_api.is_logged_in()
    if not logged_in:
        st.info("🔐 Please login to view live watchlist data.")
    else:
        ps_api = st.session_state["ps_api"]
        try:
            wl_resp = ps_api.get_watchlists()
        except Exception as e:
            st.warning(f"⚠️ Could not fetch watchlists: {e}")
            wl_resp = {}

        if wl_resp.get("stat") == "Ok":
            raw_watchlists = wl_resp["values"]
            watchlists = sorted(raw_watchlists, key=int)
            wl_labels = [f"Watchlist {wl}" for wl in watchlists]
            selected_label = st.selectbox("📁 Choose Watchlist", wl_labels)
            selected_wl = dict(zip(wl_labels, watchlists))[selected_label]

            st.session_state.all_watchlists = watchlists
            st.session_state.selected_watchlist = selected_wl

            wl_data = ps_api.get_watchlist(selected_wl)
            if wl_data.get("stat") == "Ok":
                df = pd.DataFrame(wl_data["values"])
                st.write(f"📦 {len(df)} scrips in watchlist '{selected_wl}'")
                st.dataframe(df if not df.empty else pd.DataFrame())

                symbols_with_tokens = []
                for s in wl_data["values"]:
                    token = s.get("token", "")
                    if token:
                        symbols_with_tokens.append({"tsym": s["tsym"], "exch": s["exch"], "token": token})
                st.session_state["symbols"] = symbols_with_tokens
                st.success(f"✅ {len(symbols_with_tokens)} symbols ready for WebSocket/AutoTrader")
            else:
                st.warning(wl_data.get("emsg", "Failed to load watchlist."))
        else:
            st.warning(wl_resp.get("emsg", "Could not fetch watchlists."))

# === Tab 4: Indicator Settings ===
with tab4:
    from tab4_auto_trader import render_tab4
    from tkp_trm_chart import render_trm_settings_once

    st.subheader("📀 Indicator & TRM Settings")

    # ✅ Ensure expander flag initialized BEFORE calling UI builder
    if "trm_settings_expander_rendered" not in st.session_state:
        st.session_state["trm_settings_expander_rendered"] = False

    # AutoTrader settings panel
    render_tab4(require_session_settings=True, allow_file_fallback=False)

    # TRM/MACD settings panel (safe, no duplication)
    st.markdown("---")
    render_trm_settings_once()


# === Tab 5: Strategy Engine ===
with tab5:
    st.subheader("📉 TPSeries + Live Tick Data (auto-start, blink-free)")

    # ✅ HARD STOP if not logged in (so no WebSocket / history loads trigger)
    if "ps_api" not in st.session_state or not st.session_state.ps_api.is_logged_in():
        st.info("🔐 Please login first to enable Strategy Engine.")
        st.stop()

    # --- WebSocket backend status ---
    if "ws_backend_ok" in st.session_state:
        if st.session_state["ws_backend_ok"]:
            st.success("✅ Backend WS reachable")
        else:
            st.error("❌ Backend WS unreachable — check backend_stream_server or Render URL")
    else:
        st.info("ℹ️ Backend WS status not checked yet. Login to test connection.")

    import plotly.graph_objects as go
    import threading, queue, time
    import pandas as pd, pytz

    import plotly.graph_objects as go
    import threading, queue, time
    import pandas as pd, pytz
    pd.set_option('future.no_silent_downcasting', True)
    from datetime import datetime, timedelta

    # --- Load scrips & prepare WS symbol list ---
    try:
        scrips = ps_api.get_watchlist(selected_watchlist).get("values", [])
    except Exception as e:
        st.warning("⚠️ Waiting for login & watchlist selection…")
        st.stop()

    # --- Initialize session state defaults ---
    for key, default in {
        "live_feed_flag": {"active": False},
        "ws_started": False,
        "ohlc_x": [], "ohlc_o": [], "ohlc_h": [], "ohlc_l": [], "ohlc_c": [],
        "live_fig": None,
        "last_tp_dt": None,
        "symbols_for_ws": []
    }.items():
        if key not in st.session_state:
            st.session_state[key] = default

    # --- Define Indian market holidays (with Muhurat session fix) ---
    # --- Define Indian market holidays (with Muhurat Trading exception) ---
    full_holidays = pd.to_datetime([
        "2025-02-26","2025-03-14","2025-03-31","2025-04-10","2025-04-14",
        "2025-04-18","2025-05-01","2025-08-15","2025-08-27",
        "2025-10-02","2025-10-22","2025-11-05","2025-12-25"  # 🟢 21 Oct removed
    ]).normalize()

    holiday_breaks = []

    # --- Standard full-day holidays (skip entire trading hours) ---
    for h in full_holidays:
        start = h + pd.Timedelta(hours=9, minutes=15)
        end   = h + pd.Timedelta(hours=15, minutes=30)
        holiday_breaks.append(dict(bounds=[start, end]))

    # --- Global non-trading hours (daily) ---
    holiday_breaks.append(dict(bounds=["sat", "mon"]))  # weekend
    holiday_breaks.append(dict(bounds=[15.5, 9.25], pattern="hour"))  # 15:30–09:15 off-hours

    # --- Special case: Muhurat Day (21-Oct-2025) ---
    # Normally market off, but allow 13:45–14:45 only
    muhurat_day = pd.Timestamp("2025-10-21").tz_localize("Asia/Kolkata")

    # Skip entire day except 13:45–14:45
    # Before 13:45
    holiday_breaks.append(dict(
        bounds=[
            muhurat_day.replace(hour=9, minute=15),
            muhurat_day.replace(hour=13, minute=45)
        ]
    ))
    # After 14:45
    holiday_breaks.append(dict(
        bounds=[
            muhurat_day.replace(hour=14, minute=45),
            muhurat_day.replace(hour=15, minute=30)
        ]
    ))


    # ✅ Guard clause
    if "ps_api" not in st.session_state or "selected_watchlist" not in st.session_state:
        st.warning("⚠️ Please login and select a watchlist in Tab 1 before starting live feed.")
        st.stop()

    ps_api = st.session_state.ps_api

    # UI controls
    watchlists = st.session_state.get("all_watchlists", [])
    wl_labels = [f"Watchlist {wl}" for wl in watchlists]
    current_wl = st.session_state.get("selected_watchlist", watchlists[0] if watchlists else None)
    selected_label = st.selectbox("📁 Select Watchlist for Live Feed",
                                  wl_labels,
                                  index=wl_labels.index(f"Watchlist {current_wl}") if current_wl in watchlists else 0)
    selected_watchlist = dict(zip(wl_labels, watchlists))[selected_label]
    st.session_state.selected_watchlist = selected_watchlist

    interval_options = ["1","3","5","10","15","30","60","120","240"]
    default_interval = st.session_state.get("saved_interval", "5")
    selected_interval = st.selectbox("⏱️ Candle Interval (minutes)",
                                     interval_options,
                                     index=interval_options.index(default_interval))
    if st.button("💾 Save Interval"):
        st.session_state.saved_interval = selected_interval
        st.success(f"Interval saved: {selected_interval} min")

    # --- Shared UI Queue ---
    if "ui_queue" not in st.session_state:
        st.session_state.ui_queue = queue.Queue()
    ui_queue = st.session_state.ui_queue

    # --- Placeholders ---
    placeholder_status = st.empty()
    placeholder_ticks = st.empty()
    placeholder_chart = st.empty()

    # ✅ Separate placeholder for TRM Indicator Chart (only once create)
    if "trm_placeholder" not in st.session_state:
        st.session_state["trm_placeholder"] = st.empty()
    trm_placeholder = st.session_state["trm_placeholder"]


    # --- Load scrips & prepare WS symbol list ---
    scrips = ps_api.get_watchlist(selected_watchlist).get("values", [])
    symbols_map = {f"{s['exch']}|{s['token']}": s["tsym"] for s in scrips if s.get("token")}

    if not symbols_map:
        st.warning("⚠️ No symbols found in this watchlist.")
        st.stop()

    # --- Select symbol from current watchlist ---
    symbol_keys = list(symbols_map.keys())
    symbol_labels = list(symbols_map.values())

    default_symbol = st.session_state.get("selected_symbol", symbol_keys[0])
    selected_label = st.selectbox("📌 Select Symbol", symbol_labels,
                                  index=symbol_labels.index(symbols_map.get(default_symbol, symbol_labels[0])))

    # Map back to exch|token
    selected_symbol_key = [k for k, v in symbols_map.items() if v == selected_label][0]
    st.session_state["selected_symbol"] = selected_symbol_key

    # Save mapping (needed later for ticks)
    st.session_state["symbols_map"] = symbols_map
    st.session_state["symbols_for_ws"] = [selected_symbol_key]

    # --- TPSeries fetch for selected symbol ---
    try:
        exch, token = selected_symbol_key.split("|")
        tsym = symbols_map[selected_symbol_key]
        cache_key = f"tp_{selected_symbol_key}_{selected_interval}"

        if cache_key not in st.session_state:
            st.session_state[cache_key] = ps_api.fetch_full_tpseries(
                exch, token, interval=selected_interval, max_days=5
            )

        tpseries_results = st.session_state[cache_key]

    except Exception as e:
        tpseries_results = []
        st.warning(f"TPSeries fetch error: {e}")

    # --- Figure init (only once) ---
    if st.session_state.live_fig is None:
        st.session_state.live_fig = go.Figure()
        st.session_state.live_fig.add_trace(go.Candlestick(
            x=[], open=[], high=[], low=[], close=[],
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
            name="Price"
        ))
        st.session_state.live_fig.update_layout(
            xaxis=dict(
                rangeslider_visible=False,
                type="date"
            ),
            yaxis=dict(
                fixedrange=False  # y-axis zoom allowed
            ),    
            dragmode="pan",
            hovermode="x unified",
            showlegend=False,
            template="plotly_dark",
            height=700,
            margin=dict(l=50, r=50, t=50, b=50),
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white"),
            transition_duration=0,
        )
    
    # --- Open / Close Chart buttons ---
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📊 Open Chart"):
            st.session_state["chart_open"] = True
    with col2:
        if st.button("❌ Close Chart"):
            st.session_state["chart_open"] = False

    # --- Chart placeholder (create once) ---
    if "chart_placeholder" not in st.session_state:
        st.session_state["chart_placeholder"] = st.empty()
    chart_placeholder = st.session_state["chart_placeholder"]

    # --- Chart render ---
    # === 🔄 Realtime Chart Render (TradingView-like) ===
    # --- Chart render (LIGHTWEIGHT MODE) ---
    from streamlit.components.v1 import html as st_html
    import os, requests

    if st.session_state.get("chart_open", False):

        chart_file = os.path.join("frontend", "components", "realtime_chart.html")

        if os.path.exists(chart_file):

            backend_ws_origin = st.text_input(
                "Backend WS URL",
                value="wss://backend-stream-1ij9.onrender.com/ws/live"
            )

            # ✅ Convert history → Lightweight format
            history = [
                {"time": int(x.timestamp()), "open": float(o), "high": float(h),
                 "low": float(l), "close": float(c)}
                for x, o, h, l, c in zip(
                    st.session_state.ohlc_x,
                    st.session_state.ohlc_o,
                    st.session_state.ohlc_h,
                    st.session_state.ohlc_l,
                    st.session_state.ohlc_c
                )
            ]

            # ✅ Selected token
            initial_token = st.session_state.get("selected_symbol")

            # ✅ Read HTML
            html_data = open(chart_file, "r", encoding="utf-8").read()

            # ✅ Inject history + wsUrl + token + interval
            html_data = (
                f"<script>"
                f"window.initialHistory = {history}; "
                f"window.wsUrl = '{backend_ws_origin}'; "
                f"window.initialToken = '{initial_token}'; "
                f"window.barInterval = {int(selected_interval)};"
                f"</script>"
                + html_data
            )

            # ✅ Render lightweight chart
            st_html(html_data, height=650)

            # ✅ Fire-and-forget backend subscribe (no UI button needed)
            try:
                requests.post(
                    "https://backend-stream-1ij9.onrender.com/subscribe",
                    json={"tokens": [initial_token]},
                    timeout=4
                )
            except Exception:
                pass

        else:
            st.error("❌ realtime_chart.html missing — Lightweight chart not found.")

    else:
        chart_placeholder.empty()
        st.info("ℹ️ Chart is closed. Press 'Open Chart' to view.")


    # --- Helper: write ohlc arrays into session_state and figure (without clearing history unless intended) ---
    def load_history_into_state(df_history):
        # df_history: indexed by tz-aware Asia/Kolkata datetime, cols open/high/low/close, numeric
        df_history = df_history.sort_index()
        st.session_state.ohlc_x = list(df_history.index)
        st.session_state.ohlc_o = list(df_history["open"].astype(float))
        st.session_state.ohlc_h = list(df_history["high"].astype(float))
        st.session_state.ohlc_l = list(df_history["low"].astype(float))
        st.session_state.ohlc_c = list(df_history["close"].astype(float))

        # Replace existing trace 0 with full history (blink-free)
        st.session_state.live_fig.data = []
        st.session_state.live_fig.add_trace(go.Candlestick(
            x=st.session_state.ohlc_x,
            open=st.session_state.ohlc_o,
            high=st.session_state.ohlc_h,
            low=st.session_state.ohlc_l,
            close=st.session_state.ohlc_c,
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
            name="History"
        ))
        st.session_state.last_tp_dt = st.session_state.ohlc_x[-1] if st.session_state.ohlc_x else None
    
    # === 🔧 Helper: safe_update_chart ===
    def safe_update_chart(fig, x, o, h, l, c):
        """Update Plotly candlestick without resetting layout or causing rerun"""
        if not fig.data:
            fig.add_trace(go.Candlestick(
                x=x, open=o, high=h, low=l, close=c,
                increasing_line_color="#26a69a",
                decreasing_line_color="#ef5350",
                name="Live"
            ))
        else:
            fig.data[0].x = x
            fig.data[0].open = o
            fig.data[0].high = h
            fig.data[0].low = l
            fig.data[0].close = c

    # --- Update last candle from tick (blink-free) ---
    def update_last_candle_from_tick_local(tick, interval=1):
        try:
            ts = int(tick.get("ft") or tick.get("time") or 0)
            if ts == 0:
                return
            # tick timestamp is epoch seconds UTC -> convert to IST
            dt = datetime.fromtimestamp(ts, tz=pytz.UTC).astimezone(pytz.timezone("Asia/Kolkata"))

            minute = (dt.minute // interval) * interval
            candle_time = dt.replace(second=0, microsecond=0, minute=minute)

            price = None
            if "lp" in tick and tick["lp"] not in (None, "", "NA"):
                try:
                    price = float(tick["lp"])
                except Exception:
                    price = None
            if price is None:
                return

            # if no history loaded yet, initialize with this candle
            if not st.session_state.ohlc_x:
                st.session_state.ohlc_x = [candle_time]
                st.session_state.ohlc_o = [price]
                st.session_state.ohlc_h = [price]
                st.session_state.ohlc_l = [price]
                st.session_state.ohlc_c = [price]
                st.session_state.last_tp_dt = candle_time
            else:
                # Only update if candle_time is >= last known (allow new session)
                if st.session_state.last_tp_dt is None or candle_time > st.session_state.last_tp_dt:
                    # New candle after last TPSeries candle: append
                    st.session_state.ohlc_x.append(candle_time)
                    st.session_state.ohlc_o.append(price)
                    st.session_state.ohlc_h.append(price)
                    st.session_state.ohlc_l.append(price)
                    st.session_state.ohlc_c.append(price)
                    st.session_state.last_tp_dt = candle_time
                elif candle_time == st.session_state.ohlc_x[-1]:
                    # update existing last candle values
                    st.session_state.ohlc_h[-1] = max(st.session_state.ohlc_h[-1], price)
                    st.session_state.ohlc_l[-1] = min(st.session_state.ohlc_l[-1], price)
                    st.session_state.ohlc_c[-1] = price
                else:
                    # tick older than last candle -> ignore
                    return

            # update the single trace in place (blink-free)
            if st.session_state.live_fig.data:
                trace = st.session_state.live_fig.data[0]
                trace.x = st.session_state.ohlc_x
                trace.open = st.session_state.ohlc_o
                trace.high = st.session_state.ohlc_h
                trace.low = st.session_state.ohlc_l
                trace.close = st.session_state.ohlc_c
            else:
                st.session_state.live_fig.add_trace(go.Candlestick(
                    x=st.session_state.ohlc_x,
                    open=st.session_state.ohlc_o,
                    high=st.session_state.ohlc_h,
                    low=st.session_state.ohlc_l,
                    close=st.session_state.ohlc_c,
                    increasing_line_color="#26a69a",
                    decreasing_line_color="#ef5350",
                    name="Live"
                ))

            # ✅ update existing figure without rerun
            safe_update_chart(
                st.session_state.live_fig,
                st.session_state.ohlc_x,
                st.session_state.ohlc_o,
                st.session_state.ohlc_h,
                st.session_state.ohlc_l,
                st.session_state.ohlc_c
            )

        except Exception as e:
            placeholder_ticks.warning(f"⚠️ Candle update error: {e}")

    
    # --- Preload TPSeries history and auto-start WS ---
    # --- Load history ONLY when chart is open ---
    if st.session_state.get("chart_open", False):
        wl = st.session_state.selected_watchlist
        interval = selected_interval
        try:
            tpseries_results = ps_api.fetch_tpseries_for_watchlist(wl, interval)
        except Exception as e:
            tpseries_results = []
            st.warning(f"TPSeries fetch error: {e}")

        if tpseries_results:
            df = tpseries_results[0]["data"].copy()

            if "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
                df["datetime"] = df["datetime"].dt.tz_localize(
                    "Asia/Kolkata", nonexistent="shift_forward", ambiguous="NaT"
                )
                df = df.dropna(subset=["datetime"]).set_index("datetime")

                if "into" in df.columns and "open" not in df.columns:
                    df = df.rename(columns={
                        "into": "open", "inth": "high", "intl": "low",
                        "intc": "close", "intv": "volume"
                    })

                for col in ["open", "high", "low", "close", "volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(subset=["open", "high", "low", "close"])

                load_history_into_state(df)
                st.write(f"📊 Loaded TPSeries candles: {len(df)}")

                if "holiday_values" not in st.session_state or "holiday_breaks" not in st.session_state:
                    holiday_values = [pd.Timestamp(h).to_pydatetime().replace(tzinfo=None) for h in full_holidays]
                    holiday_breaks = []
                    for h in full_holidays:
                        start = pd.Timestamp(h).tz_localize("Asia/Kolkata").replace(hour=9, minute=15)
                        end   = pd.Timestamp(h).tz_localize("Asia/Kolkata").replace(hour=15, minute=30)
                        holiday_breaks.append(dict(
                            bounds=[start.to_pydatetime().replace(tzinfo=None),
                                    end.to_pydatetime().replace(tzinfo=None)]
                        ))
                    st.session_state.holiday_values = holiday_values
                    st.session_state.holiday_breaks = holiday_breaks
                else:
                    holiday_values = st.session_state.holiday_values
                    holiday_breaks = st.session_state.holiday_breaks

                st.session_state.live_fig.update_xaxes(
                    showgrid=True, gridwidth=0.5, gridcolor="gray",
                    type="date", tickformat="%d-%m-%Y\n%H:%M", tickangle=0,
                    rangeslider_visible=False,
                    rangebreaks=[dict(bounds=["sat","mon"]), dict(bounds=[15.5,9.25], pattern="hour"), *holiday_breaks]
                )
            else:
                st.error("⚠️ No datetime column in TPSeries data")
        else:
            st.warning("⚠️ No TPSeries data fetched")

    # ✅ AUTO START LIVE FEED (No Start Button Needed)
    from tab4_auto_trader import start_ws

    # ✅ HARD STOP: No WS UNTIL login confirmed
    if "ps_api" not in st.session_state or not st.session_state.ps_api.is_logged_in():
        st.info("🔐 Please login first to start live feed.")
        st.stop()

    # ✅ HARD STOP: No WS UNTIL a watchlist symbol is selected
    if "symbols_for_ws" not in st.session_state or not st.session_state["symbols_for_ws"]:
        st.info("⚠️ Select symbol above to start live feed.")
        st.stop()

    # ✅ Start WS only when chart is actually opened
    if st.session_state.get("chart_open", False) and not st.session_state.get("ws_started", False):
        if "_ws_stop_event" not in st.session_state:
            st.session_state["_ws_stop_event"] = threading.Event()
        try:
            ws = start_ws(
                st.session_state["symbols_for_ws"],
                st.session_state["ps_api"],
                st.session_state["ui_queue"],
                st.session_state["_ws_stop_event"]
            )
            st.session_state["ws"] = ws
            st.session_state.live_feed_flag["active"] = True
            st.session_state.ws_started = True
            st.success(f"📡 Live Feed Started")

        except Exception as e:
            st.error(f"❌ WebSocket start failed: {e}")

    # ✅ Stop WS only when chart actually closed
    if not st.session_state.get("chart_open", False) and st.session_state.get("ws_started", False):
        try:
            st.session_state["_ws_stop_event"].set()
        except:
            pass
        st.session_state.live_feed_flag["active"] = False
        st.session_state.ws_started = False

    # --- Drain queue and apply live ticks to last candle ---
    # This block runs each script run and consumes queued ticks (non-blocking)
    if st.session_state.live_feed_flag.get("active", False):
        processed = 0; 
        last_tick = None
        for _ in range(500):  # consume up to N ticks each run
            try:
                msg_type, payload = ui_queue.get_nowait()
            except queue.Empty:
                break
            else:
                if msg_type == "tick":
                    update_last_candle_from_tick_local(payload, interval=int(selected_interval))
                    processed += 1
                    last_tick = payload
                elif msg_type == "heartbeat":
                    st.session_state.last_heartbeat = payload
                elif msg_type == "ws_error":
                    placeholder_status.error(f"WS start error: {payload}")

        placeholder_status.info(
            f"WS started: {st.session_state.get('ws_started', False)} | "
            f"symbols: {len(st.session_state.get('symbols_for_ws', []))} | "
            f"queue: {ui_queue.qsize()} | processed: {processed} | "
            f"display_len: {len(st.session_state.ohlc_x)}"
        )
        if "last_heartbeat" in st.session_state:
            placeholder_status.info(f"📡 Last heartbeat: {st.session_state.last_heartbeat}")
            
        if processed == 0 and ui_queue.qsize() == 0 and (not st.session_state.ohlc_x):
            placeholder_ticks.info("⏳ Waiting for first ticks...")

    # --- "Go to latest" control uses ohlc_x as source of truth ---
    # Fix OHLC column names if needed
    if "into" in df.columns and "open" not in df.columns:
        df = df.rename(columns={
            "into": "open", "inth": "high", "intl": "low", "intc": "close", "intv": "volume"
        })

    # Convert numeric
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])

    # ✅ LOAD HISTORY HERE (outside loop)
    st.session_state.live_fig.update_yaxes(
        showgrid=True, gridwidth=0.5, gridcolor="gray", fixedrange=False
    )

    # ✅ Separate placeholder for Indicator Chart (only once create)

    from tkp_trm_chart import plot_trm_chart, get_trm_settings_safe
    from plotly.subplots import make_subplots

    st.markdown("---")
    st.markdown("### 🟣 TRM + PAC + MACD Indicator Panel (Static, No Blink)")

    if st.button("🟣 Show TRM + MACD Indicators"):

        if len(st.session_state.ohlc_x) >= 50:
            # 1) Convert session_state → DataFrame
            df_live = pd.DataFrame({
                "datetime": pd.to_datetime(st.session_state.ohlc_x),
                "open": st.session_state.ohlc_o,
                "high": st.session_state.ohlc_h,
                "low": st.session_state.ohlc_l,
                "close": st.session_state.ohlc_c
            })

            # ✅ Timezone normalize (IST) + make tz-naive
            if df_live["datetime"].dt.tz is None:
                df_live["datetime"] = df_live["datetime"].dt.tz_localize("Asia/Kolkata")
            else:
                df_live["datetime"] = df_live["datetime"].dt.tz_convert("Asia/Kolkata")
            df_live["datetime"] = df_live["datetime"].apply(lambda x: x.replace(tzinfo=None))

            # ✅ Clean and sort
            df_live = (
                df_live.drop_duplicates(subset="datetime")
                       .sort_values("datetime")
                       .reset_index(drop=True)
            )

            # ✅ Build/restore rangebreaks for holidays + weekends + off hours
            if "holiday_values" not in st.session_state or "holiday_breaks" not in st.session_state:
                holiday_values = [
                    pd.Timestamp(h).tz_localize("Asia/Kolkata").date().isoformat()
                    for h in full_holidays
                ]
                holiday_breaks = []
                for h in full_holidays:
                    start = pd.Timestamp(h).tz_localize("Asia/Kolkata").replace(hour=9, minute=15)
                    end   = pd.Timestamp(h).tz_localize("Asia/Kolkata").replace(hour=15, minute=30)
                    start_naive = start.tz_convert(None)
                    end_naive   = end.tz_convert(None)
                    holiday_breaks.append(dict(bounds=[start_naive, end_naive]))

                st.session_state.holiday_values = holiday_values
                st.session_state.holiday_breaks = holiday_breaks
            else:
                holiday_breaks = st.session_state.holiday_breaks

            rangebreaks = [
                dict(bounds=["sat", "mon"]),                # weekends skip
                dict(bounds=[15.5, 9.25], pattern="hour"),  # non-market time skip
                *holiday_breaks                              # holidays skip
            ]
            st.session_state["rangebreaks_obj"] = rangebreaks

            # ✅ Load TRM settings & render indicator figure
            settings = get_trm_settings_safe()
            fig_trm = plot_trm_chart(
                df_live,
                settings,
                rangebreaks=rangebreaks,
                fig=None,
                show_macd_panel=True
            )

            trm_placeholder.plotly_chart(fig_trm, use_container_width=True)

        else:
            st.warning("⚠️ Need at least 50 candles for TRM indicators.\nIncrease TPSeries max_days or choose larger interval.")


























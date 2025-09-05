
# main_app.py
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

# === Page Layout ===
st.set_page_config(page_title="Auto Intraday Trading", layout="wide")
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
                    st.success("✅ Login successful!")
                    st.rerun()
                else:
                    st.error(f"❌ Login failed: {msg}")
            except Exception as e:
                st.error(f"❌ Exception: {e}")

if "ps_api" in st.session_state:
    if st.sidebar.button("🔓 Logout"):
        del st.session_state["ps_api"]
        st.success("✅ Logged out successfully")
        st.rerun()

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

# === Tab 2: Dashboard ===
with tab2:
    st.subheader("📊 Dashboard")
    st.info("Coming soon...")

# === Tab 3: Market Data ===
with tab3:
    st.subheader("📈 Live Market Table – Watchlist Viewer")

    if "ps_api" in st.session_state:
        ps_api = st.session_state["ps_api"]
        wl_resp = ps_api.get_watchlists()
        if wl_resp.get("stat") == "Ok":
            raw_watchlists = wl_resp["values"]
            watchlists = sorted(raw_watchlists, key=int)
            wl_labels = [f"Watchlist {wl}" for wl in watchlists]
            selected_label = st.selectbox("📁 Choose Watchlist", wl_labels)
            selected_wl = dict(zip(wl_labels, watchlists))[selected_label]

            wl_data = ps_api.get_watchlist(selected_wl)
            if wl_data.get("stat") == "Ok":
                df = pd.DataFrame(wl_data["values"])
                st.write(f"📦 {len(df)} scrips in watchlist '{selected_wl}'")
                st.dataframe(df if not df.empty else pd.DataFrame())
            else:
                st.warning(wl_data.get("emsg", "Failed to load watchlist."))
        else:
            st.warning(wl_resp.get("emsg", "Could not fetch watchlists."))
    else:
        st.info("ℹ️ Please login to view live watchlist data.")

# === Tab 4: Indicator Settings ===
with tab4:
    st.info("📀 Indicator settings section coming soon...")

# === Function: TPSeries fetch in daily chunks (fix for single candle issue) ===
def fetch_full_tpseries(api, exch, token, interval, days=60):
    final_df = pd.DataFrame()

    # IST timezone
    ist_offset = timedelta(hours=5, minutes=30)
    today_ist = datetime.utcnow() + ist_offset
    end_dt = today_ist
    start_dt = end_dt - timedelta(days=days)

    current_day = start_dt
    while current_day <= end_dt:
        day_start = current_day.replace(hour=9, minute=15, second=0, microsecond=0)
        day_end = current_day.replace(hour=15, minute=30, second=0, microsecond=0)

        # Convert to epoch seconds (UTC)
        st_epoch = int((day_start - ist_offset).timestamp())
        et_epoch = int((day_end - ist_offset).timestamp())

        resp = api.get_tpseries(exch, token, interval, st_epoch, et_epoch)

        if isinstance(resp, dict) and resp.get("stat") == "Ok" and "values" in resp:
            chunk_df = pd.DataFrame(resp["values"])
            chunk_df["datetime"] = pd.to_datetime(chunk_df["time"], unit="s", utc=True) + ist_offset
            chunk_df.set_index("datetime", inplace=True)
            final_df = pd.concat([final_df, chunk_df])
        else:
            # Weekend/holiday skip message
            pass  

        current_day += timedelta(days=1)
        time.sleep(0.3)  # Avoid rate limit

    final_df.sort_index(inplace=True)
    return final_df

# === Tab 5: Strategy Engine ===
with tab5:
    st.subheader("📉 TPSeries + Live Tick Data (blink-free)")

    import plotly.graph_objects as go
    import threading, queue, time
    import pandas as pd
    from datetime import datetime

    # --- Shared UI Queue ---
    if "ui_queue" not in st.session_state:
        st.session_state.ui_queue = queue.Queue()
    ui_queue = st.session_state.ui_queue

    # --- Persistent Plotly FigureWidget ---
    if "live_fig" not in st.session_state:
        st.session_state.live_fig = go.FigureWidget()
        st.session_state.live_fig.add_candlestick(
            x=[], open=[], high=[], low=[], close=[],
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350',
            name="Price"
        )
        st.session_state.live_fig.update_layout(
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            height=700,
            transition_duration=0  # blink-free
        )
        st.session_state.ohlc_x = []
        st.session_state.ohlc_o = []
        st.session_state.ohlc_h = []
        st.session_state.ohlc_l = []
        st.session_state.ohlc_c = []

    # --- Placeholders ---
    placeholder_status = st.empty()
    placeholder_ticks = st.empty()
    placeholder_chart = st.empty()
    placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)

    # --- Thread-safe live flag ---
    if "live_feed_flag" not in st.session_state:
        st.session_state.live_feed_flag = {"active": False}

    # --- Update candle from live tick ---
    def update_last_candle_from_tick(tick: dict, interval: int = 1):
        if not tick:
            return
        try:
            ts = int(float(tick.get("ft", time.time())))
        except:
            ts = int(time.time())
        try:
            vol = int(float(tick.get("v", 0) or 0))
        except:
            vol = 0
        m = int(interval)
        bucket_ts = ts - (ts % (m * 60))
        key = f"{tick.get('e')}|{tick.get('tk')}|{m}"

        if "live_candles" not in st.session_state:
            st.session_state.live_candles = {}
        if key not in st.session_state.live_candles:
            st.session_state.live_candles[key] = {}

        # --- Maintain OHLC arrays ---
        if "ohlc_x" not in st.session_state:
            st.session_state.ohlc_x = []
            st.session_state.ohlc_o = []
            st.session_state.ohlc_h = []
            st.session_state.ohlc_l = []
            st.session_state.ohlc_c = []

        last_close = st.session_state.ohlc_c[-1] if st.session_state.ohlc_c else 0.0
        price = float(tick.get("lp") or tick.get("c") or last_close)

        if bucket_ts not in st.session_state.live_candles[key]:
            st.session_state.live_candles[key][bucket_ts] = {"ts": bucket_ts, "o": price, "h": price, "l": price, "c": price, "v": vol}
            st.session_state.ohlc_x.append(pd.to_datetime(bucket_ts, unit="s"))
            st.session_state.ohlc_o.append(price)
            st.session_state.ohlc_h.append(price)
            st.session_state.ohlc_l.append(price)
            st.session_state.ohlc_c.append(price)
        else:
            cndl = st.session_state.live_candles[key][bucket_ts]
            cndl["c"] = price
            cndl["h"] = max(cndl["h"], price)
            cndl["l"] = min(cndl["l"], price)
            cndl["v"] += vol
            st.session_state.ohlc_o[-1] = cndl["o"]
            st.session_state.ohlc_h[-1] = cndl["h"]
            st.session_state.ohlc_l[-1] = cndl["l"]
            st.session_state.ohlc_c[-1] = cndl["c"]

        # Limit last 200 candles
        st.session_state.ohlc_x = st.session_state.ohlc_x[-200:]
        st.session_state.ohlc_o = st.session_state.ohlc_o[-200:]
        st.session_state.ohlc_h = st.session_state.ohlc_h[-200:]
        st.session_state.ohlc_l = st.session_state.ohlc_l[-200:]
        st.session_state.ohlc_c = st.session_state.ohlc_c[-200:]

        # Update FigureWidget trace
        trace = st.session_state.live_fig.data[0]
        trace.x = st.session_state.ohlc_x
        trace.open = st.session_state.ohlc_o
        trace.high = st.session_state.ohlc_h
        trace.low = st.session_state.ohlc_l
        trace.close = st.session_state.ohlc_c

    # --- Tick Consumer Thread ---
    if "consumer_thread" not in st.session_state or not st.session_state.consumer_thread.is_alive():
        def live_tick_consumer(live_feed_flag, ui_queue, placeholder_ticks, placeholder_status):
            while live_feed_flag["active"]:
                last_tick = None
                processed = 0
                while not ui_queue.empty():
                    try:
                        tick = ui_queue.get_nowait()
                        update_last_candle_from_tick(tick)
                        last_tick = tick
                        processed += 1
                    except queue.Empty:
                        break
                # Update placeholders
                if last_tick:
                    placeholder_ticks.json(last_tick)
                    placeholder_status.info(f"Ticks processed: {processed} | Total candles: {len(st.session_state.ohlc_x)}")
                else:
                    placeholder_status.info("⏳ Waiting for ticks...")
                time.sleep(0.5)

        st.session_state.consumer_thread = threading.Thread(
            target=live_tick_consumer,
            args=(st.session_state.live_feed_flag, ui_queue, placeholder_ticks, placeholder_status),
            daemon=True
        )
        st.session_state.consumer_thread.start()

    # --- WebSocket starter ---
    def start_ws(symbols, ps_api, ui_queue):
        def on_tick_callback(tick):
            try:
                ui_queue.put(tick, block=False)
            except:
                pass
        ps_api.connect_websocket(symbols, on_tick=on_tick_callback, tick_file="ticks_tab5.log")

    # --- Login check ---
    if "ps_api" not in st.session_state:
        st.warning("⚠️ Please login first.")
        st.stop()
    ps_api = st.session_state["ps_api"]

    # --- Watchlist selection ---
    wl_resp = ps_api.get_watchlists()
    if wl_resp.get("stat") != "Ok":
        st.warning(wl_resp.get("emsg", "Could not fetch watchlists."))
        st.stop()
    raw_watchlists = wl_resp["values"]
    watchlists = sorted(raw_watchlists, key=int)
    selected_watchlist = st.selectbox("Select Watchlist", watchlists)
    selected_interval = st.selectbox("Select Interval", ["1","3","5","10","15","30","60","120","240"], index=0)

    # --- Start / Stop Feed Buttons ---
    if st.button("🚀 Start TPSeries + Live Feed"):
        st.session_state.live_feed_flag["active"] = True
        scrips = ps_api.get_watchlist(selected_watchlist).get("values", [])
        symbols_for_ws = [f"{s['exch']}|{s['token']}" for s in scrips]
        if symbols_for_ws:
            threading.Thread(target=start_ws, args=(symbols_for_ws, ps_api, ui_queue), daemon=True).start()
            st.info(f"📡 Live feed started for {len(symbols_for_ws)} symbols.")
        else:
            st.info("No symbols to start WS for.")

    if st.button("🛑 Stop Live Feed"):
        st.session_state.live_feed_flag["active"] = False
        st.info("🛑 Live feed stopped.")

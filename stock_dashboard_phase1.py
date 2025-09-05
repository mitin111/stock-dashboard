
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
    st.subheader("📉 TPSeries + Live Tick Data (debug mode)")

    # local imports (ok inside block for Streamlit)
    import plotly.graph_objects as go
    import threading, queue, time
    import pandas as pd
    from datetime import datetime

    # --- Init shared UI Queue ---
    if "ui_queue" not in st.session_state:
        st.session_state.ui_queue = queue.Queue()
    ui_queue = st.session_state.ui_queue

    # --- Persistent Plotly Figure ---
    if "live_fig" not in st.session_state:
        st.session_state.live_fig = go.Figure()
        st.session_state.live_fig.add_trace(
            go.Candlestick(
                x=[],
                open=[],
                high=[],
                low=[],
                close=[],
                increasing_line_color='#26a69a',
                decreasing_line_color='#ef5350',
                name="Price",
            )
        )
        st.session_state.live_fig.update_layout(
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            height=700,
        )

    if "live_feed" not in st.session_state:
        st.session_state.live_feed = False

    # --- Debug placeholders ---
    placeholder_status = st.empty()
    placeholder_ticks = st.empty()
    placeholder_chart = st.empty()

    # -----------------------------
    # Update candle from live tick (non-blinking update)
    # -----------------------------
    def update_last_candle_from_tick(tick: dict, interval: int):
        try:
            # Safely get price and timestamp from tick
            price = float(tick.get("lp") or tick.get("bp1") or tick.get("sp1") or 0)
            ts = int(tick.get("ft", 0) or tick.get("lt", 0) or 0)
            if price == 0 or ts == 0:
                return

            # Ensure OHLC arrays exist
            if "ohlc_x" not in st.session_state:
                st.session_state.ohlc_x = []
                st.session_state.ohlc_o = []
                st.session_state.ohlc_h = []
                st.session_state.ohlc_l = []
                st.session_state.ohlc_c = []

            # bucket timestamp to interval (interval given in minutes)
            bucket_secs = int(interval) * 60
            bucket_ts = (ts // bucket_secs) * bucket_secs
            bucket_time = pd.to_datetime(bucket_ts, unit="s")

            # If last candle in same bucket -> update, else append new candle
            if st.session_state.ohlc_x and st.session_state.ohlc_x[-1] == bucket_time:
                st.session_state.ohlc_h[-1] = max(st.session_state.ohlc_h[-1], price)
                st.session_state.ohlc_l[-1] = min(st.session_state.ohlc_l[-1], price)
                st.session_state.ohlc_c[-1] = price
            else:
                st.session_state.ohlc_x.append(bucket_time)
                st.session_state.ohlc_o.append(price)
                st.session_state.ohlc_h.append(price)
                st.session_state.ohlc_l.append(price)
                st.session_state.ohlc_c.append(price)

            # keep only last 200 candles
            st.session_state.ohlc_x = st.session_state.ohlc_x[-200:]
            st.session_state.ohlc_o = st.session_state.ohlc_o[-200:]
            st.session_state.ohlc_h = st.session_state.ohlc_h[-200:]
            st.session_state.ohlc_l = st.session_state.ohlc_l[-200:]
            st.session_state.ohlc_c = st.session_state.ohlc_c[-200:]

            # 🔥 update chart trace arrays (without re-creating fig)
            fig = st.session_state.live_fig
            fig.data[0].x = st.session_state.ohlc_x
            fig.data[0].open = st.session_state.ohlc_o
            fig.data[0].high = st.session_state.ohlc_h
            fig.data[0].low = st.session_state.ohlc_l
            fig.data[0].close = st.session_state.ohlc_c

        except Exception as e:
            # show error in UI so debugging is easier
            st.error(f"Update candle error: {e}")

    # --- Sirf last tick process karna ---
    def consume_last_tick(interval):
        """
        Drain the ui_queue and process only the latest ticks.
        This will loop through the queue and update last candle for each tick.
        """
        if "ui_queue" not in st.session_state:
            return
        q = st.session_state.ui_queue
        if q.empty():
            return

        # ✅ Purane ticks clear karo, sab process karke sirf latest rakh lo in display
        while not q.empty():
            try:
                tick = q.get_nowait()
            except queue.Empty:
                break
            # update candle from this tick
            try:
                update_last_candle_from_tick(tick, int(interval))
            except Exception as e:
                # don't crash the loop if one tick fails
                print(f"consume_last_tick update error: {e}")

            # Append tick to display list (keep last 200)
            if "ticks_display" not in st.session_state:
                st.session_state.ticks_display = []
            st.session_state.ticks_display.append(tick)
            st.session_state.ticks_display = st.session_state.ticks_display[-200:]

    # --- WS forwarder ---
    def start_ws(symbols, ps_api, ui_queue):
        """
        Starts websocket via ps_api and forwards incoming ticks to ui_queue using on_tick_callback.
        """
        def on_tick_callback(tick):
            try:
                ui_queue.put(tick, block=False)
            except Exception as e:
                print(f"⚠️ WS callback error: {e}")

        # ps_api should expose a connect_websocket(symbols, on_tick=..., tick_file=...) method
        ps_api.connect_websocket(symbols, on_tick=on_tick_callback, tick_file="ticks_tab5.log")
        print("▶ WS started with callback")

    # --- UI logic and PS API checks ---
    if "ps_api" not in st.session_state:
        st.warning("⚠️ Please login first.")
        st.stop()
    ps_api = st.session_state["ps_api"]

    wl_resp = ps_api.get_watchlists()
    if wl_resp.get("stat") != "Ok":
        st.warning(wl_resp.get("emsg", "Could not fetch watchlists."))
        st.stop()
    raw_watchlists = wl_resp["values"]
    watchlists = sorted(raw_watchlists, key=int)
    selected_watchlist = st.selectbox("Select Watchlist", watchlists)

    selected_interval = st.selectbox(
        "Select Interval",
        ["1", "3", "5", "10", "15", "30", "60", "120", "240"],
        index=0,
    )

    # --- Start / Stop buttons ---
    if st.button("🚀 Start TPSeries + Live Feed"):
        st.session_state.live_feed = True
        st.session_state.ws_started = False

    if st.button("🛑 Stop Live Feed"):
        st.session_state.live_feed = False

    # --- Start WS and load TPSeries if not already started ---
    if st.session_state.live_feed and not st.session_state.get("ws_started", False):
        with st.spinner("Fetching TPSeries (60 days) and starting WS..."):
            scrips = ps_api.get_watchlist(selected_watchlist).get("values", [])
            symbols_for_ws = []

            for scrip in scrips:
                exch, token, tsym = scrip.get("exch"), scrip.get("token"), scrip.get("tsym")
                try:
                    df_candle = ps_api.fetch_full_tpseries(exch, token, interval=selected_interval, chunk_days=60)
                except Exception as e:
                    st.warning(f"TPSeries fetch error for {tsym}: {e}")
                    continue

                if df_candle is None or df_candle.empty:
                    st.info(f"No TPSeries for {tsym}")
                    continue

                # try to find the datetime column robustly
                date_cols = [c for c in df_candle.columns if "date" in c.lower() or "time" in c.lower()]
                if not date_cols:
                    st.info(f"No datetime column found for {tsym}")
                    continue

                df_candle["datetime"] = pd.to_datetime(df_candle[date_cols[0]], errors="coerce")
                df_candle.dropna(subset=["datetime"], inplace=True)
                df_candle.sort_values("datetime", inplace=True)

                # Initialize session OHLC arrays + live_fig with historical TPSeries
                st.session_state.ohlc_x = list(df_candle["datetime"])
                st.session_state.ohlc_o = list(df_candle["open"].astype(float))
                st.session_state.ohlc_h = list(df_candle["high"].astype(float))
                st.session_state.ohlc_l = list(df_candle["low"].astype(float))
                st.session_state.ohlc_c = list(df_candle["close"].astype(float))

                # update the figure trace arrays
                st.session_state.live_fig.data[0].x = st.session_state.ohlc_x
                st.session_state.live_fig.data[0].open = st.session_state.ohlc_o
                st.session_state.live_fig.data[0].high = st.session_state.ohlc_h
                st.session_state.live_fig.data[0].low = st.session_state.ohlc_l
                st.session_state.live_fig.data[0].close = st.session_state.ohlc_c

                placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)

                symbols_for_ws.append(f"{exch}|{token}")

            if symbols_for_ws:
                threading.Thread(target=start_ws, args=(symbols_for_ws, ps_api, ui_queue), daemon=True).start()
                st.session_state.ws_started = True
                st.session_state.symbols_for_ws = symbols_for_ws
            else:
                st.info("No symbols to start WS for.")

    # --- Consumer loop: sirf last tick update ---
    if st.session_state.live_feed:
        # Initialize some counters/containers if missing
        if "processed_count" not in st.session_state:
            st.session_state.processed_count = 0
        if "ticks_display" not in st.session_state:
            st.session_state.ticks_display = []

        # Process latest ticks from queue (drain quickly)
        consume_last_tick(selected_interval)

        # Update chart (no blinking since fig persists)
        placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True, key="livechart")

        # Status
        qsize = st.session_state.ui_queue.qsize() if "ui_queue" in st.session_state else 0
        placeholder_status.info(
            f"WS started: {st.session_state.get('ws_started', False)} | "
            f"symbols: {len(st.session_state.get('symbols_for_ws', []))} | "
            f"queue: {qsize} | "
            f"display_len: {len(st.session_state.ticks_display)}"
        )

        # Show ticks table
        if st.session_state.ticks_display:
            df_ticks_show = pd.DataFrame(st.session_state.ticks_display[-50:])
            placeholder_ticks.dataframe(df_ticks_show.tail(10), use_container_width=True)
        else:
            placeholder_ticks.info("⏳ Waiting for first ticks...")
    else:
        # when not live, show the last loaded chart if exists
        if "live_fig" in st.session_state:
            placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)
        placeholder_status.info("Live feed stopped.")

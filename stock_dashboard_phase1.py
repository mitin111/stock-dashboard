
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

    import plotly.graph_objects as go
    import threading, queue, time
    import pandas as pd
    from datetime import datetime

    # --- Persistent Plotly Figure (only once) ---
    if "live_fig" not in st.session_state:
        st.session_state.live_fig = go.Figure()
        st.session_state.live_fig.add_trace(go.Candlestick(
            x=[], open=[], high=[], low=[], close=[],
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350',
            name="Price"
        ))
        st.session_state.live_fig.update_layout(
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            height=700
        )

    if "live_feed" not in st.session_state:
        st.session_state.live_feed = False

    # --- Debug placeholders ---
    placeholder_status = st.empty()
    placeholder_ticks = st.empty()
    placeholder_chart = st.empty()

    # --- Minimal last-candle updater ---
    def update_last_candle_from_tick(tick, selected_interval, placeholder_chart):
        if not tick or not tick.get("lp"):
            return
        try:
            price = float(tick["lp"])
        except:
            return

        ts = int(float(tick.get("ft", time.time())))
        vol = int(float(tick.get("v", 0)))

        m = int(selected_interval)
        bucket_ts = ts - (ts % (m * 60))
        key = f"{tick.get('e')}|{tick.get('tk')}|{m}"

        if "live_candles" not in st.session_state:
            st.session_state.live_candles = {}
        if key not in st.session_state.live_candles:
            st.session_state.live_candles[key] = {}

        fig = st.session_state.live_fig
        fig.data[0].x = list(fig.data[0].x)
        fig.data[0].open = list(fig.data[0].open)
        fig.data[0].high = list(fig.data[0].high)
        fig.data[0].low = list(fig.data[0].low)
        fig.data[0].close = list(fig.data[0].close)

        if bucket_ts not in st.session_state.live_candles[key]:
            # New candle
            st.session_state.live_candles[key][bucket_ts] = {
                "ts": bucket_ts, "o": price, "h": price,
                "l": price, "c": price, "v": vol
            }
            fig.data[0].x.append(pd.to_datetime(bucket_ts, unit="s"))
            fig.data[0].open.append(price)
            fig.data[0].high.append(price)
            fig.data[0].low.append(price)
            fig.data[0].close.append(price)
        else:
            # Update existing candle
            cndl = st.session_state.live_candles[key][bucket_ts]
            cndl["c"] = price
            cndl["h"] = max(cndl["h"], price)
            cndl["l"] = min(cndl["l"], price)
            cndl["v"] += vol
            idx = -1
            if fig.data[0].close:
                fig.data[0].open[idx] = cndl["o"]
                fig.data[0].high[idx] = cndl["h"]
                fig.data[0].low[idx] = cndl["l"]
                fig.data[0].close[idx] = cndl["c"]

        # keep last 200 candles
        fig.data[0].x = fig.data[0].x[-200:]
        fig.data[0].open = fig.data[0].open[-200:]
        fig.data[0].high = fig.data[0].high[-200:]
        fig.data[0].low = fig.data[0].low[-200:]
        fig.data[0].close = fig.data[0].close[-200:]

        placeholder_chart.plotly_chart(fig, use_container_width=True)

    # --- WS forwarder (callback pushes directly to UI queue) ---
    def start_ws(symbols, ps_api, ui_queue):
        def on_tick_callback(tick):
            print("📩 Raw tick arrived (Tab5):", tick)
            try:
                # ✅ Always push to UI queue (both types)
                ui_queue.put({"type": "raw_tick", "data": tick})
                ui_queue.put({"type": "raw_tick_display", "data": tick})
            except Exception as e:
                print("⚠️ on_tick_callback error:", e)

        ps_api.connect_websocket(symbols, on_tick=on_tick_callback, tick_file="ticks_tab5.log")
        print("▶ start_ws called from Tab5 with callback")

    # --- UI logic ---
    if "ps_api" not in st.session_state:
        st.warning("⚠️ Please login first using your API credentials.")
        st.stop()
    ps_api = st.session_state["ps_api"]

    if "ui_queue" not in st.session_state:
        st.session_state.ui_queue = queue.Queue()
    ui_queue = st.session_state.ui_queue

    wl_resp = ps_api.get_watchlists()
    if wl_resp.get("stat") != "Ok":
        st.warning(wl_resp.get("emsg", "Could not fetch watchlists."))
        st.stop()

    raw_watchlists = wl_resp["values"]
    watchlists = sorted(raw_watchlists, key=int)
    selected_watchlist = st.selectbox("Select Watchlist", watchlists)
    selected_interval = st.selectbox("Select Interval", ["1","3","5","10","15","30","60","120","240"], index=0)

    if st.button("🚀 Start TPSeries + Live Feed"):
        st.session_state.live_feed = True
        st.session_state.ws_started = False
    if st.button("🛑 Stop Live Feed"):
        st.session_state.live_feed = False

    if st.session_state.live_feed and not st.session_state.get("ws_started", False):
        with st.spinner("Fetching TPSeries (60 days) and starting WS..."):
            scrips = ps_api.get_watchlist(selected_watchlist).get("values", [])
            symbols_for_ws = []
            for scrip in scrips:
                exch, token, tsym = scrip["exch"], scrip["token"], scrip["tsym"]
                try:
                    df_candle = ps_api.fetch_full_tpseries(exch, token, interval=selected_interval, chunk_days=60)
                except Exception as e:
                    st.warning(f"TPSeries fetch error for {tsym}: {e}")
                    continue
                if df_candle is None or df_candle.empty:
                    st.info(f"No TPSeries for {tsym}")
                    continue

                df_candle["datetime"] = pd.to_datetime(
                    df_candle[df_candle.columns[df_candle.columns.str.contains("date|time")][0]], 
                    errors="coerce"
                )
                df_candle.dropna(subset=["datetime"], inplace=True)
                df_candle.sort_values("datetime", inplace=True)

                key = f"{exch}|{token}|{selected_interval}"
                if not hasattr(ps_api, "candles") or ps_api.candles is None:
                    ps_api.candles = {}
                ps_api.candles[key] = {}
                for _, row in df_candle.iterrows():
                    ts_epoch = int(row["datetime"].timestamp())
                    ps_api.candles[key][ts_epoch] = {
                        "ts": ts_epoch, "o": float(row["open"]), "h": float(row["high"]),
                        "l": float(row["low"]), "c": float(row["close"]),
                        "v": int(row.get("volume", 0))
                    }

                st.session_state.live_fig.data[0].x = list(df_candle["datetime"])
                st.session_state.live_fig.data[0].open = list(df_candle["open"])
                st.session_state.live_fig.data[0].high = list(df_candle["high"])
                st.session_state.live_fig.data[0].low = list(df_candle["low"])
                st.session_state.live_fig.data[0].close = list(df_candle["close"])
                placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)

                symbols_for_ws.append(f"{exch}|{token}")

            if symbols_for_ws:
                threading.Thread(target=start_ws, args=(symbols_for_ws, ps_api, ui_queue), daemon=True).start()
                st.session_state.ws_started = True
                st.session_state.symbols_for_ws = symbols_for_ws
            else:
                st.info("No symbols to start WS for.")

    # --- Consumer ---
    if st.session_state.live_feed:
        if "processed_count" not in st.session_state:
            st.session_state.processed_count = 0
        if "ticks_display" not in st.session_state:
            st.session_state.ticks_display = []

        while not st.session_state.ui_queue.empty():
            item = st.session_state.ui_queue.get_nowait()
            try:
                if isinstance(item, dict) and item.get("type") == "raw_tick":
                    raw = item.get("data")
                    if raw:
                        update_last_candle_from_tick(raw, selected_interval, placeholder_chart)
                        st.session_state.processed_count += 1
                elif isinstance(item, dict) and item.get("type") == "raw_tick_display":
                    st.session_state.ticks_display.append(item["data"])
                else:
                    st.session_state.ticks_display.append(item)
            except Exception as e:
                print("⚠️ consumer loop error:", e)

        # --- Status update ---
        placeholder_status.info(
            f"WS started: {st.session_state.get('ws_started', False)} | "
            f"symbols: {len(st.session_state.get('symbols_for_ws', []))} | "
            f"queue: {st.session_state.ui_queue.qsize()} | "
            f"processed: {st.session_state.processed_count}"
        )

        # ✅ Always show last ticks
        if st.session_state.ticks_display:
            df_ticks_show = pd.DataFrame(st.session_state.ticks_display[-50:])
            placeholder_ticks.dataframe(df_ticks_show.tail(10), use_container_width=True)
        else:
            placeholder_ticks.info("⏳ Waiting for live ticks...")

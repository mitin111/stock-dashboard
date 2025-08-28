
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
                st.session_state["last_error"] = wl_data.get("emsg", "Failed to load watchlist.")
        else:
            st.session_state["last_error"] = wl_resp.get("emsg", "Could not fetch watchlists.")
    else:
        st.info("ℹ️ Please login to view live watchlist data.")

    # ✅ Safe error render
    if "last_error" in st.session_state:
        st.warning(st.session_state["last_error"])
        del st.session_state["last_error"]

# === Tab 4: Indicator Settings ===
with tab4:
    st.info("📀 Indicator settings section coming soon...")

# === Tab 5: Strategy Engine ===
with tab5:
    st.subheader("📉 TPSeries + Live Tick Data")

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import threading, queue
    import pandas as pd

    # --- Helper: Plot Candles ---
    def plot_tpseries_candles(df, symbol):
        df = df.drop_duplicates(subset=['datetime']).sort_values("datetime")
        df = df[(df['datetime'].dt.time >= pd.to_datetime("09:15").time()) &
                (df['datetime'].dt.time <= pd.to_datetime("15:30").time())]

        fig = make_subplots(rows=1, cols=1, shared_xaxes=True)
        fig.add_trace(go.Candlestick(
            x=df['datetime'],
            open=df['open'], high=df['high'],
            low=df['low'], close=df['close'],
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350',
            name='Price'
        ))

        fig.update_layout(
            xaxis_rangeslider_visible=False,
            dragmode='pan',
            hovermode='x unified',
            showlegend=False,
            template="plotly_dark",
            height=700,
            margin=dict(l=50, r=50, t=50, b=50),
            plot_bgcolor='black',
            paper_bgcolor='black',
            font=dict(color='white'),
            title=f"{symbol} - TradingView-style Chart"
        )
        fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='gray')
        fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor='gray', fixedrange=False)
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]),
                                      dict(bounds=[15.5, 9.25], pattern="hour")])
        return fig

    # --- WebSocket Start Helper ---
    def start_ws(symbols):
        if "tick_queue" not in st.session_state:
            st.session_state.tick_queue = queue.Queue()

        def on_tick_callback(tick):
            try:
                st.session_state.tick_queue.put(tick)
            except Exception as e:
                print("⚠️ tick_queue error:", e)

        ps_api._on_tick = on_tick_callback
        ps_api.connect_websocket(symbols)

    # --- UI ---
    if "ps_api" not in st.session_state:
        st.warning("⚠️ Please login first using your API credentials.")
    else:
        ps_api = st.session_state["ps_api"]
        wl_resp = ps_api.get_watchlists()

        if wl_resp.get("stat") == "Ok":
            raw_watchlists = wl_resp["values"]
            watchlists = sorted(raw_watchlists, key=int)
            selected_watchlist = st.selectbox("Select Watchlist", watchlists)
            selected_interval = st.selectbox(
                "Select Interval",
                ["1", "3", "5", "10", "15", "30", "60", "120", "240"]
            )

            placeholder_ticks = st.empty()   # Live tick table
            placeholder_chart = st.empty()   # Live candle chart

            if st.button("🚀 Start TPSeries + Live Feed"):
                with st.spinner("Fetching TPSeries + starting WebSocket..."):
                    wl_data = ps_api.get_watchlist(selected_watchlist)
                    if wl_data.get("stat") == "Ok":
                        scrips = wl_data.get("values", [])
                        symbols_for_ws = []

                        for i, scrip in enumerate(scrips):
                            exch, token, tsym = scrip["exch"], scrip["token"], scrip["tsym"]
                            st.write(f"📦 {i+1}. {tsym} → {exch}|{token}")

                            try:
                                df_candle = ps_api.fetch_full_tpseries(
                                    exch, token,
                                    interval=selected_interval,
                                    chunk_days=5
                                )
                                if not df_candle.empty:
                                    if "datetime" not in df_candle.columns:
                                        for col in ["time", "date"]:
                                            if col in df_candle.columns:
                                                df_candle.rename(columns={col: "datetime"}, inplace=True)

                                    df_candle["datetime"] = pd.to_datetime(
                                        df_candle["datetime"],
                                        format="%d-%m-%Y %H:%M:%S",
                                        errors="coerce",
                                        dayfirst=True
                                    )
                                    df_candle.dropna(subset=["datetime"], inplace=True)
                                    df_candle.sort_values("datetime", inplace=True)

                                    # Plot chart once initially
                                    fig = plot_tpseries_candles(df_candle, tsym)
                                    placeholder_chart.plotly_chart(fig, use_container_width=True)
                                    st.dataframe(df_candle, use_container_width=True, height=500)

                                    symbols_for_ws.append(f"{exch}|{token}")

                                else:
                                    st.warning(f"⚠️ No data for {tsym}")

                            except Exception as e:
                                st.warning(f"⚠️ {tsym}: Exception occurred - {e}")

                        st.success(f"✅ TPSeries fetched for {len(symbols_for_ws)} scrips")

                        # Start WebSocket in background (once)
                        if symbols_for_ws and "ws_started" not in st.session_state:
                            threading.Thread(target=start_ws, args=(symbols_for_ws,), daemon=True).start()
                            st.session_state.ws_started = True
                            st.info(f"🔗 WebSocket started for {len(symbols_for_ws)} symbols")

            # --- ✅ Safe Live Tick Consumer (MERGED HERE) ---
            if "tick_queue" in st.session_state:
                ticks = []
                while not st.session_state.tick_queue.empty():
                    ticks.append(st.session_state.tick_queue.get())

                if ticks:
                    if "df_ticks" not in st.session_state:
                        st.session_state.df_ticks = pd.DataFrame(ticks)
                    else:
                        st.session_state.df_ticks = pd.concat(
                            [st.session_state.df_ticks, pd.DataFrame(ticks)]
                        ).tail(2000)   # ✅ keep last 2000 rows

                    # 🔹 Tick table update
                    placeholder_ticks.dataframe(
                        st.session_state.df_ticks.tail(10),
                        use_container_width=True
                    )

                    # 🔹 Candle chart update
                    df = st.session_state.df_ticks.copy()
                    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
                    df.dropna(subset=["datetime"], inplace=True)

                    if not df.empty:
                        fig = plot_tpseries_candles(df, "LIVE")
                        placeholder_chart.plotly_chart(fig, use_container_width=True)

                else:
                    placeholder_ticks.info("⏳ Waiting for live ticks...")

        else:
            st.session_state["last_error"] = wl_resp.get("emsg", "Could not fetch watchlists.")

    # ✅ Safe error render
    if "last_error" in st.session_state:
        st.warning(st.session_state["last_error"])
        del st.session_state["last_error"]

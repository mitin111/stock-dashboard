
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


# ================================
# WebSocket Status Line
# ================================
import queue
tick_queue = queue.Queue()
status_placeholder = st.empty()

if "last_tick_time" not in st.session_state:
    st.session_state.last_tick_time = None
if "ws_status" not in st.session_state:
    st.session_state.ws_status = "🔴 Disconnected"

def on_open(ws):
    st.session_state.ws_status = "🟡 Connected (waiting for ticks)"
    status_placeholder.info(st.session_state.ws_status)

def on_close(ws, close_status_code, close_msg):
    st.session_state.ws_status = "🔴 Disconnected"
    status_placeholder.error(st.session_state.ws_status)

def on_message(ws, message):
    # Jab bhi tick aaye
    st.session_state.last_tick_time = time.time()
    st.session_state.ws_status = "🟢 Connected & Receiving Live Data"
    status_placeholder.success(st.session_state.ws_status)

def check_market_status():
    if st.session_state.last_tick_time:
        if time.time() - st.session_state.last_tick_time > 30:
            st.session_state.ws_status = "🟡 Connected but Market Closed"
            status_placeholder.warning(st.session_state.ws_status)


# === Tab 5: Strategy Engine ===
with tab5:
    st.subheader("📉 TPSeries Data Preview + Live Update")

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    # --- Chart Plotter ---
    def plot_tpseries_candles(df, symbol):
        df = df.drop_duplicates(subset=['Datetime'])
        df = df.sort_values("Datetime")

        # Market hours filter (09:15 - 15:30)
        df = df[
            (df['Datetime'].dt.time >= pd.to_datetime("09:15").time()) &
            (df['Datetime'].dt.time <= pd.to_datetime("15:30").time())
        ]

        fig = make_subplots(rows=1, cols=1, shared_xaxes=True)

        fig.add_trace(go.Candlestick(
            x=df['Datetime'],
            open=df['Open'],
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
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
        )
        fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='gray')
        fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor='gray', fixedrange=False)

        # Hide weekends + non-market hours
        fig.update_xaxes(
            rangebreaks=[
                dict(bounds=["sat", "mon"]),
                dict(bounds=[15.5, 9.25], pattern="hour")
            ]
        )

        # ✅ Go-to-latest button
        fig.update_layout(
            updatemenus=[
                dict(
                    type="buttons",
                    direction="left",
                    x=1,
                    y=1.15,
                    buttons=[
                        dict(
                            label="Go to Latest",
                            method="relayout",
                            args=[{"xaxis.range": [df['Datetime'].iloc[-50], df['Datetime'].iloc[-1]]}]
                        )
                    ]
                )
            ],
            title=f"{symbol} - TradingView-style Chart"
        )
        return fig

    # --- Streamlit workflow ---
    if "ps_api" not in st.session_state:
        st.warning("⚠️ Please login first using your API credentials.")
    else:
        ps_api = st.session_state["ps_api"]

        # Fetch all watchlists
        wl_resp = ps_api.get_watchlists()
        if wl_resp.get("stat") == "Ok":
            raw_watchlists = wl_resp["values"]
            watchlists = sorted(raw_watchlists, key=int)
            selected_watchlist = st.selectbox("Select Watchlist", watchlists)
            selected_interval = st.selectbox(
                "Select Interval",
                ["1", "3", "5", "10", "15", "30", "60", "120", "240"]
            )

            chart_placeholder = st.empty()

            if st.button("🔁 Fetch TPSeries Data"):
                with st.spinner("Fetching candle data..."):
                    wl_data = ps_api.get_watchlist(selected_watchlist)
                    if wl_data.get("stat") == "Ok":
                        scrips = wl_data.get("values", [])
                        if not scrips:
                            st.warning("⚠️ No scrips found in this watchlist.")
                        else:
                            # Take first scrip for live chart demo
                            scrip = scrips[0]
                            exch, token, tsym = scrip["exch"], scrip["token"], scrip["tsym"]

                            # Step 1: Historical fetch
                            df_candle = ps_api.fetch_full_tpseries(
                                exch, token,
                                interval=selected_interval,
                                chunk_days=5
                            )
                            if not df_candle.empty:
                                # ✅ Fix: Rename columns properly
                                df_candle.rename(
                                    columns={
                                        "datetime": "Datetime",
                                        "open": "Open",
                                        "high": "High",
                                        "low": "Low",
                                        "close": "Close",
                                        "volume": "Volume"
                                    },
                                    inplace=True
                                )
                                df_candle["Datetime"] = pd.to_datetime(df_candle["Datetime"])

                                # Step 2: Save in session
                                st.session_state["candles_df"] = df_candle.copy()
                                st.session_state["live_symbol"] = f"{exch}|{token}"

                                # ✅ Step 3: Start WebSocket for live ticks (queue-based)
                                ps_api.start_websocket_for_symbol(
                                    st.session_state["live_symbol"],
                                    on_open=on_open,
                                    on_close=on_close,
                                    on_message=on_message,
                                    tick_queue=tick_queue  # 👈 new param
                                )
                                st.success(f"✅ TPSeries fetched & live updates started for {tsym}")

                            else:
                                st.warning(f"⚠️ No candle data available for {tsym}")

                    else:
                        st.warning(wl_data.get("emsg", "Failed to load watchlist."))

            # --- Process Queue & Auto-refresh chart ---
            if "candles_df" in st.session_state and not st.session_state["candles_df"].empty:
                # 🔹 Process new ticks
                while not tick_queue.empty():
                    new_candle = tick_queue.get()
                    df = st.session_state.get("candles_df", pd.DataFrame())

                    if not df.empty and df.iloc[-1]["Datetime"] == new_candle["Datetime"]:
                        df.at[df.index[-1], "High"] = max(df.iloc[-1]["High"], new_candle["High"])
                        df.at[df.index[-1], "Low"] = min(df.iloc[-1]["Low"], new_candle["Low"])
                        df.at[df.index[-1], "Close"] = new_candle["Close"]
                        df.at[df.index[-1], "Volume"] += new_candle["Volume"]
                    else:
                        df = pd.concat([df, pd.DataFrame([new_candle])], ignore_index=True)

                    st.session_state["candles_df"] = df

                # 🔹 Status check
                check_market_status()

                # 🔹 Plot chart
                fig = plot_tpseries_candles(
                    st.session_state["candles_df"],
                    st.session_state.get("live_symbol", "Unknown")
                )
                chart_placeholder.plotly_chart(fig, use_container_width=True)
                st.dataframe(st.session_state["candles_df"].tail(50), use_container_width=True, height=400)

        else:
            st.warning(wl_resp.get("emsg", "Could not fetch watchlists."))


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

def plot_candlestick_from_api(raw_data, symbol):
    import pandas as pd
    df = pd.DataFrame(raw_data)

    df.rename(columns={
        "time": "datetime",
        "into": "open",
        "inth": "high",
        "intl": "low",
        "intc": "close",
        "intv": "volume"
    }, inplace=True)

    df["datetime"] = pd.to_datetime(df["datetime"], format="%d-%m-%Y %H:%M:%S", errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df.dropna(subset=["datetime"], inplace=True)
    df.sort_values("datetime", inplace=True)

    fig = go.Figure(data=[go.Candlestick(
        x=df["datetime"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name=symbol
    )])

    fig.update_layout(
        title=f"{symbol} - Live Candlestick Chart",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=500
    )

    st.plotly_chart(fig, use_container_width=True)

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
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["🏠 Home", "📋 Orders", "📈 Market Data", "⚙ Settings", "💹 Trades & Chart", "📊 Candlestick Charts"]
)

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
    st.subheader("📉 TPSeries Data Preview")

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

            if st.button("🔁 Fetch TPSeries Data"):
                with st.spinner("Fetching candle data for all scrips..."):
                    wl_data = ps_api.get_watchlist(selected_watchlist)
                    if wl_data.get("stat") == "Ok":
                        scrips = wl_data.get("values", [])
                        call_count = 0
                        delay_per_call = 1.1

                        for i, scrip in enumerate(scrips):
                            exch = scrip["exch"]
                            token = scrip["token"]
                            tsym = scrip["tsym"]
                            st.write(f"📦 {i+1}. {tsym} → {exch}|{token}")

                            try:
                                df_candle = ps_api.fetch_full_tpseries(
                                    exch, token,
                                    interval=selected_interval,
                                    chunk_days=5
                                )

                                if not df_candle.empty and 'time' in df_candle.columns:
                                    try:
                                        # Convert string time (DD-MM-YYYY HH:MM:SS) to datetime
                                        df_candle['datetime'] = pd.to_datetime(
                                            df_candle['time'],
                                            format='%d-%m-%Y %H:%M:%S',
                                            errors='coerce'
                                        )

                                        # Drop invalid dates
                                        df_candle = df_candle.dropna(subset=['datetime'])

                                        # Remove duplicate timestamps if any
                                        df_candle = df_candle.drop_duplicates(
                                            subset=['datetime'], keep='last'
                                        )

                                        # Sort oldest to newest
                                        df_candle = df_candle.sort_values(
                                            by='datetime', ascending=True
                                        ).reset_index(drop=True)

                                    except Exception as e:
                                        st.warning(f"⚠️ {tsym}: Datetime conversion failed - {e}")

                                    st.dataframe(df_candle, use_container_width=True, height=600)
                                else:
                                    st.warning(f"⚠️ No data for {tsym}")

                            except Exception as e:
                                st.warning(f"⚠️ {tsym}: Exception occurred - {e}")

                            call_count += 1
                            time.sleep(delay_per_call)

                        st.success(f"✅ Fetched TPSeries for {call_count} scrips in '{selected_watchlist}'")
                    else:
                        st.warning(wl_data.get("emsg", "Failed to load watchlist data."))
        else:
            st.warning(wl_resp.get("emsg", "Could not fetch watchlists."))

    # === Candlestick Chart (Tab 5) ===
    st.subheader("📈 Candlestick Chart (Tab 5)")
    if "ps_api" in st.session_state:
        selected_symbol_tab5 = st.selectbox(
            "Select Scrip for Chart", df["tsym"].unique(), key="tab5_symbol"
        )
        if st.button("Show Chart (Tab 5)"):
            try:
                raw_candle_data = ps_api.get_ohlcv(selected_symbol_tab5)
                if raw_candle_data and isinstance(raw_candle_data, list):
                    plot_candlestick_from_api(raw_candle_data, selected_symbol_tab5)
                else:
                    st.warning("No candle data received for this symbol.")
            except Exception as e:
                st.error(f"Error fetching candlestick data: {e}")
    else:
        st.warning("⚠️ Please login first using your API credentials.")


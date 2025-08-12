
# === stock_dashboard_phase1.py ===

import streamlit as st
import pandas as pd
from prostocks_connector import ProStocksAPI, fetch_tpseries, make_empty_candle, update_candle
from dashboard_logic import load_settings, save_settings, load_credentials
from datetime import datetime
import time
import plotly.graph_objects as go
import logging
logging.basicConfig(level=logging.DEBUG)

# === Page Config ===
st.set_page_config(page_title="Auto Intraday Trading + TPSeries", layout="wide")
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
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "⚙️ Trade Controls",
    "📊 Dashboard",
    "📈 Market Data",
    "📀 Indicator Settings",
    "📉 Strategy Engine",
    "📉 Live Candlestick"
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

            st.markdown("---")
            st.subheader("🔍 Search & Modify Watchlist")
            search_query = st.text_input("Search Symbol or Keyword")
            if search_query:
                sr = ps_api.search_scrip(search_query)
                if sr.get("stat") == "Ok" and sr.get("values"):
                    scrip_df = pd.DataFrame(sr["values"])
                    scrip_df["display"] = scrip_df["tsym"] + " (" + scrip_df["exch"] + "|" + scrip_df["token"] + ")"
                    selected_rows = st.multiselect("Select Scrips", scrip_df.index, format_func=lambda i: scrip_df.loc[i, "display"])
                    selected_scrips = [f"{scrip_df.loc[i, 'exch']}|{scrip_df.loc[i, 'token']}" for i in selected_rows]

                    col1, col2 = st.columns(2)
                    if col1.button("➕ Add to Watchlist") and selected_scrips:
                        resp = ps_api.add_scrips_to_watchlist(selected_wl, selected_scrips)
                        st.success(f"✅ Added: {resp}")
                        st.rerun()
                    if col2.button("➖ Delete from Watchlist") and selected_scrips:
                        resp = ps_api.delete_scrips_from_watchlist(selected_wl, selected_scrips)
                        st.success(f"✅ Deleted: {resp}")
                        st.rerun()
                else:
                    st.info("No matching scrips found.")
        else:
            st.warning(wl_resp.get("emsg", "Could not fetch watchlists."))
    else:
        st.info("ℹ️ Please login to view live watchlist data.")

# === Tab 4: Indicator Settings ===
with tab4:
    st.info("📀 Indicator settings section coming soon...")

# === Tab 5: Strategy Engine ===
with tab5:
    st.info("📉 Strategy engine section coming soon...")

# Tab 6 – Auto Watchlist Multi-Chart View
with tab6:
    st.subheader("📊 Multi-Chart View (Historical TPSeries Data)")

    if 'api' not in st.session_state:
        st.error("⚠️ Please login first to use Multi-Chart tab.")
    else:
        api = st.session_state['api']  # ✅ FIX for NameError

        watchlist_name = st.text_input("Enter Watchlist Name", "WATCHLIST_1")
        if st.button("Load Watchlist & Charts"):
            watchlist_symbols = api.get_watchlist(watchlist_name)
            if not watchlist_symbols:
                st.warning("⚠️ No symbols found in watchlist.")
            else:
                st.write(f"✅ Found {len(watchlist_symbols)} symbols in {watchlist_name}")

                st_date = st.date_input("Start Date")
                et_date = st.date_input("End Date")
                interval = st.selectbox("Interval", ["1", "3", "5", "15", "30", "60"], index=2)

                st_unix = int(time.mktime(datetime.combine(st_date, datetime.min.time()).timetuple()))
                et_unix = int(time.mktime(datetime.combine(et_date, datetime.max.time()).timetuple()))

                for sym in watchlist_symbols:
                    exch = sym['exch']
                    token = sym['token']
                    data = api.get_tpseries(exch, token, st_unix, et_unix, interval)
                    if not data or 'candles' not in data:
                        st.warning(f"No data for {sym['symbol']}")
                        continue

                    df = pd.DataFrame(data['candles'], columns=["datetime", "open", "high", "low", "close", "volume"])
                    fig = go.Figure(data=[go.Candlestick(
                        x=pd.to_datetime(df['datetime']),
                        open=df['open'], high=df['high'],
                        low=df['low'], close=df['close']
                    )])
                    fig.update_layout(title=f"{sym['symbol']} - {interval}min")
                    st.plotly_chart(fig, use_container_width=True)

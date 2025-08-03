
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

# === Page Layout ===
st.set_page_config(page_title="Auto Intraday Trading", layout="wide")
st.title("\ud83d\udcc8 Automated Intraday Trading System")

# === Load Settings (once) ===
if "settings_loaded" not in st.session_state:
    st.session_state.update(load_settings())
    st.session_state["settings_loaded"] = True

# === Load Credentials ===
creds = load_credentials()

# === Sidebar Login ===
with st.sidebar:
    st.header("\ud83d\udd10 ProStocks OTP Login")
    if st.button("\ud83d\udce9 Send OTP"):
        temp_api = ProStocksAPI(**creds)
        success, msg = temp_api.login("")
        st.success("\u2705 OTP Sent") if success else st.info(f"\u2139\ufe0f {msg}")

    with st.form("LoginForm"):
        uid = st.text_input("User ID", value=creds["uid"])
        pwd = st.text_input("Password", type="password", value=creds["pwd"])
        factor2 = st.text_input("OTP from SMS/Email")
        vc = st.text_input("Vendor Code", value=creds["vc"] or uid)
        api_key = st.text_input("API Key", type="password", value=creds["api_key"])
        imei = st.text_input("MAC Address", value=creds["imei"])
        base_url = st.text_input("Base URL", value=creds["base_url"])
        apkversion = st.text_input("APK Version", value=creds["apkversion"])

        submitted = st.form_submit_button("\ud83d\udd10 Login")
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
                    st.success("\u2705 Login successful!")
                    st.rerun()
                else:
                    st.error(f"\u274c Login failed: {msg}")
            except Exception as e:
                st.error(f"\u274c Exception: {e}")

if "ps_api" in st.session_state:
    if st.sidebar.button("\ud83d\udd13 Logout"):
        del st.session_state["ps_api"]
        st.success("\u2705 Logged out successfully")
        st.rerun()

# === Tabs ===
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "\u2699\ufe0f Trade Controls",
    "\ud83d\udcca Dashboard",
    "\ud83d\udcc8 Market Data",
    "\ud83d\udcc0 Indicator Settings",
    "\ud83d\udcc9 Strategy Engine"
])

# === Tab 1: Trade Controls ===
with tab1:
    st.subheader("\u2699\ufe0f Step 0: Trading Control Panel")
    master = st.toggle("\u2705 Master Auto Buy + Sell", st.session_state.get("master_auto", True), key="master_toggle")
    auto_buy = st.toggle("\u25b6\ufe0f Auto Buy Enabled", st.session_state.get("auto_buy", True), key="auto_buy_toggle")
    auto_sell = st.toggle("\ud83d\udd3d Auto Sell Enabled", st.session_state.get("auto_sell", True), key="auto_sell_toggle")

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
    st.subheader("\ud83d\udcca Dashboard")
    st.info("Coming soon...")

# === Tab 3: Market Data ===
with tab3:
    st.subheader("\ud83d\udcc8 Live Market Table – Watchlist Viewer")

    if "ps_api" in st.session_state:
        ps_api = st.session_state["ps_api"]
        wl_resp = ps_api.get_watchlists()
        if wl_resp.get("stat") == "Ok":
            raw_watchlists = wl_resp["values"]
            watchlists = sorted(raw_watchlists, key=int)
            wl_labels = [f"Watchlist {wl}" for wl in watchlists]
            selected_label = st.selectbox("\ud83d\udcc1 Choose Watchlist", wl_labels)
            selected_wl = dict(zip(wl_labels, watchlists))[selected_label]

            wl_data = ps_api.get_watchlist(selected_wl)
            if wl_data.get("stat") == "Ok":
                df = pd.DataFrame(wl_data["values"])
                st.write(f"\ud83d\udce6 {len(df)} scrips in watchlist '{selected_wl}'")
                st.dataframe(df if not df.empty else pd.DataFrame())
            else:
                st.warning(wl_data.get("emsg", "Failed to load watchlist."))

# === Tab 5: Strategy Engine ===
with tab5:
    st.subheader("\ud83d\udcc9 Strategy Engine")

    if "ps_api" in st.session_state:
        ps_api = st.session_state["ps_api"]

        intrv = st.selectbox("\ud83d\udd52 Choose Candle Interval", ["1", "3", "5", "10", "15", "30"], index=2)
        if st.button("\ud83d\udd4f Save Interval"):
            st.session_state["selected_intrv"] = intrv
            st.success(f"Saved interval: {intrv} min")

        saved_intrv = st.session_state.get("selected_intrv", "5")
        st.markdown(f"\u2705 Current Interval: **{saved_intrv} min**")

        watchlists = ["5", "3", "1"]
        MAX_CALLS_PER_MIN = 100
        delay_per_call = 60 / MAX_CALLS_PER_MIN
        call_count = 0

        for wl in watchlists:
            st.markdown(f"### \ud83d\udccb Watchlist {wl}")
            symbols = ps_api.get_watchlist(wl)
            if not symbols or "values" not in symbols:
                st.warning(f"\u26a0\ufe0f No symbols found in watchlist {wl}")
                continue

            for sym in symbols["values"]:
                if call_count >= MAX_CALLS_PER_MIN:
                    st.warning("\u26a0\ufe0f TPSeries limit reached. Skipping remaining.")
                    break

                tsym = sym["tsym"]
                token = sym["token"]
                exch = sym["exch"]

                now = datetime.now()
                et = calendar.timegm(now.timetuple())
                st_time = now - timedelta(minutes=int(saved_intrv) * 3)
                st_epoch = calendar.timegm(st_time.timetuple())

                jdata = {
                    "uid": ps_api.userid,
                    "exch": exch,
                    "token": token,
                    "st": st_epoch,
                    "et": et,
                    "intrv": saved_intrv
                }

                payload = {
                    "jData": json.dumps(jdata, separators=(',', ':')),
                    "jKey": ps_api.session_token
                }

                headers = {
                    "Content-Type": "application/x-www-form-urlencoded"
                }

                response = requests.post(
                    url=ps_api.base_url + "/TPSeries",
                    data=payload,
                    headers=headers
                )

                try:
                    result = response.json()
                except Exception:
                    st.error(f"\u274c TPSeries failed for {tsym}: Invalid JSON response")
                    continue

                call_count += 1
                time.sleep(delay_per_call)

                if not isinstance(result, list):
                    st.error(f"\u274c TPSeries failed for {tsym}: {result.get('emsg', 'Unknown error')}")
                    continue

                df = pd.DataFrame(result)
                df = df[df["stat"] == "Ok"]
                if df.empty:
                    st.warning("No valid candle data found.")
                    continue

                df["time"] = pd.to_datetime(df["time"], format="%d-%m-%Y %H:%M:%S")
                df.set_index("time", inplace=True)
                df.sort_index(inplace=True)

                for col in ["into", "inth", "intl", "intc"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

                st.line_chart(df[["intc"]], height=150)

                last_price = df["intc"].iloc[-1]
                if last_price > df["inth"].mean():
                    st.success(f"\ud83d\udfe2 BUY Trigger at {last_price}")
                elif last_price < df["intl"].mean():
                    st.error(f"\ud83d\udd34 SELL Trigger at {last_price}")
                else:
                    st.info("\ud83d\udcca No action taken")

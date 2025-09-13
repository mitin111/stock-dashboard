
import streamlit as st
import pandas as pd
from datetime import datetime
import pytz

# ✅ REST + WS imports
from prostocks_connector import ProStocksAPI
from prostocks_ws import ProStocksWS

# ✅ Settings & helpers
from dashboard_logic import load_settings, save_settings, load_credentials
from dashboard_helpers import (
    render_trade_controls,
    render_dashboard,
    render_market_data,
    render_indicator_settings,
    render_strategy_engine
)

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
        temp_api = ProStocksREST(**creds)
        resp = temp_api.send_otp()
        if resp.get("stat") == "Ok":
            st.success("✅ OTP Sent")
        else:
            st.error(f"❌ {resp.get('emsg', resp)}")

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
                ps_api = ProStocksREST(
                    userid=uid, password_plain=pwd, vc=vc,
                    api_key=api_key, imei=imei,
                    base_url=base_url, apkversion=apkversion
                )
                success, msg = ps_api.login(factor2)
                if success:
                    st.session_state["ps_api"] = ps_api
                    st.success("✅ Login successful!")

                    # 🔗 WebSocket init
                    st.session_state["ps_ws"] = ProStocksWS(ps_api.userid, ps_api.session_token)

                    st.rerun()
                else:
                    st.error(f"❌ Login failed: {msg}")
            except Exception as e:
                st.error(f"❌ Exception: {e}")

if "ps_api" in st.session_state:
    if st.sidebar.button("🔓 Logout"):
        del st.session_state["ps_api"]
        if "ps_ws" in st.session_state:
            del st.session_state["ps_ws"]
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

with tab1: render_trade_controls()
with tab2: render_dashboard()
with tab3: render_market_data()
with tab4: render_indicator_settings()
with tab5: render_strategy_engine()





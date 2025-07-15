
# stock_dashboard_clean.py

import streamlit as st
from dotenv import load_dotenv
import os
import pandas as pd
from datetime import datetime, timedelta
from prostocks_connector import ProStocksAPI  # ✅ Load your custom API connector
from utils.data_fetcher import fetch_live_data  # ✅ If you have helper file
from utils.indicators import calculate_indicators  # ✅ If moved to a separate file

# ✅ Load environment variables
load_dotenv()
DEFAULT_UID = os.getenv("PROSTOCKS_UID", "")
DEFAULT_PWD = os.getenv("PROSTOCKS_PWD", "")
DEFAULT_FACTOR2 = os.getenv("PROSTOCKS_FACTOR2", "")
DEFAULT_VC = os.getenv("PROSTOCKS_VC", "")
DEFAULT_API_KEY = os.getenv("PROSTOCKS_API_KEY", "")
DEFAULT_IMEI = os.getenv("PROSTOCKS_IMEI", "")
APKVERSION = "1.0"

APPROVED_STOCK_LIST = ["RECLTD", "LTFOODS", "HINDCOPPER", "VEDL", "JIOFIN", "GSPL"]  # Replace with full list

# ✅ Streamlit page config
st.set_page_config(page_title="📈 Stock Dashboard", layout="wide")

# ✅ Sidebar Login
with st.sidebar:
    st.header("🔐 ProStocks Login")
    with st.form("ProStocksLoginForm"):
        uid = st.text_input("User ID", value=DEFAULT_UID)
        pwd = st.text_input("Password", type="password", value=DEFAULT_PWD)
        factor2 = st.text_input("2FA / DOB", value=DEFAULT_FACTOR2)
        vc = st.text_input("Vendor Code", value=DEFAULT_VC)
        api_key = st.text_input("API Key", value=DEFAULT_API_KEY)
        imei = st.text_input("IMEI", value=DEFAULT_IMEI)
        base_url = st.text_input("Base URL", value="https://api.prostocks.com")
        submitted = st.form_submit_button("Login")

        if submitted:
            try:
                ps_api = ProStocksAPI(uid, pwd, factor2, vc, api_key, imei, base_url, APKVERSION)
                success, msg = ps_api.login()
                if success:
                    st.session_state["ps_api"] = ps_api
                    st.success("✅ Login successful!")
                else:
                    st.error(f"❌ Login failed: {msg}")
            except Exception as e:
                st.error(f"⚠️ Error: {e}")

# ✅ After login
if "ps_api" in st.session_state and st.session_state["ps_api"]:
    st.title("📊 Stock Dashboard")

    # Select a stock
    symbol = st.selectbox("Select Stock", sorted(APPROVED_STOCK_LIST), key="select_stock_main")

    # Fetch & display data
    if st.button("Fetch Data"):
        df = fetch_live_data(symbol)
        st.write(f"Live Data for {symbol}", df.tail(5))

        # Calculate & display indicators
        df = calculate_indicators(df)
        st.write("📊 Indicators", df.tail(5))
else:
    st.warning("🔒 Please login to access the dashboard.")

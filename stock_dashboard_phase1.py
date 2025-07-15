
# stock_dashboard_clean.py

from prostocks_connector import ProStocksAPI
import streamlit as st
from dotenv import load_dotenv
import os
import pandas as pd
import ta  # Make sure ta is installed: pip install ta
import yfinance as yf  # ✅ Add this line to fix 'yf not defined' error


# Load credentials from .env
load_dotenv()
DEFAULT_BASE_URL = os.getenv("PROSTOCKS_BASE_URL", "https://starapiuat.prostocks.com/NorenWClientTP")

DEFAULT_UID = os.getenv("PROSTOCKS_USER_ID", "")
DEFAULT_PWD = os.getenv("PROSTOCKS_PASSWORD", "")
DEFAULT_FACTOR2 = os.getenv("PROSTOCKS_FACTOR2", "")
DEFAULT_VC = os.getenv("PROSTOCKS_VENDOR_CODE", "")
DEFAULT_API_KEY = os.getenv("PROSTOCKS_API_KEY", "")
DEFAULT_MAC = os.getenv("PROSTOCKS_MAC", "MAC123456")
DEFAULT_APK_VERSION = os.getenv("PROSTOCKS_APK_VERSION", "1.0.0")  # ✅ NEW LINE


# Sidebar Login Form (only one)
with st.sidebar:
    st.header("🔐 ProStocks Login")
    with st.form("ProStocksLoginForm"):
        uid = st.text_input("User ID", value=DEFAULT_UID)
        pwd = st.text_input("Password", type="password", value=DEFAULT_PWD)
        factor2 = st.text_input("PAN / DOB (DD-MM-YYYY)", value=DEFAULT_FACTOR2)
        vc = st.text_input("Vendor Code", value=DEFAULT_VC or DEFAULT_UID)
        api_key = st.text_input("API Key", type="password", value=DEFAULT_API_KEY)
        imei = st.text_input("MAC Address", value=DEFAULT_MAC)
        base_url = st.text_input("ProStocks Base URL", value=DEFAULT_BASE_URL)
        apkversion = st.text_input("APK Version", value=DEFAULT_APK_VERSION)  # ✅ NEW FIELD

        submitted = st.form_submit_button("🔐 Login")

        if submitted:
            try:
                ps_api = ProStocksAPI(uid, pwd, factor2, vc, api_key, imei, base_url, apkversion)  # ✅ pass apkversion
                success, msg = ps_api.login()

                if success:
                    st.session_state["ps_api"] = ps_api
                    st.success("✅ Login Successful")
                    st.rerun()
                else:
                    st.error(f"❌ Login failed: {msg}")
            except Exception as e:
                st.error(f"❌ Exception during login: {e}")


st.title("📈 ProStocks Trading Dashboard")
if "ps_api" in st.session_state:
    ps_api = st.session_state["ps_api"]
    st.title("📊 Stock Trading Dashboard")
    st.success("Dashboard loaded successfully!")
else:
   ps_api = st.session_state.get("ps_api", None)


if "ps_api" in st.session_state:
    ps_api = st.session_state["ps_api"]
    
    # ✅ If authenticated, show dashboard
    st.title("📊 Stock Trading Dashboard")
    st.success("Dashboard loaded successfully!")
else:
    st.warning("🔒 Please login to continue.")


    # ✅ Placeholder for your screener/engine logic
    st.markdown("🚀 Ready to run your stock screener, signal engine, and auto trading? Add logic here.")


           

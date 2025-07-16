
import streamlit as st
import os
import pandas as pd
from dotenv import load_dotenv
from prostocks_connector import ProStocksAPI
import json

# === Path to save settings
SETTINGS_FILE = "dashboard_settings.json"

# === Load settings from file
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {
        "master_auto": True,
        "auto_buy": True,
        "auto_sell": True
    }

# === Save settings to file
def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

# 🧱 Set page config
st.set_page_config(page_title="Auto Intraday Trading", layout="wide")
st.title("📈 Automated Intraday Trading System")

# 🔐 Load environment
load_dotenv()

# ✅ Approved stock list
APPROVED_STOCK_LIST = [
    "LTFOODS", "HSCL", "REDINGTON", "FIRSTCRY", "GSPL", "ATGL", "HEG", "RAYMOND", "GUJGASLTD",
    "TRITURBINE", "ADANIPOWER", "ELECON", "JIOFIN", "USHAMART", "INDIACEM", "HINDPETRO", "SONATSOFTW"
]

# 🔒 Load credentials
DEFAULT_UID = os.getenv("PROSTOCKS_USER_ID", "")
DEFAULT_PWD = os.getenv("PROSTOCKS_PASSWORD", "")
DEFAULT_FACTOR2 = os.getenv("PROSTOCKS_FACTOR2", "")
DEFAULT_VC = os.getenv("PROSTOCKS_VENDOR_CODE", "")
DEFAULT_API_KEY = os.getenv("PROSTOCKS_API_KEY", "")
DEFAULT_MAC = os.getenv("PROSTOCKS_MAC", "MAC123456")
DEFAULT_BASE_URL = os.getenv("PROSTOCKS_BASE_URL", "https://starapi.prostocks.com/NorenWClientTP")
DEFAULT_APK_VERSION = os.getenv("PROSTOCKS_APK_VERSION", "1.0.0")

# 🔐 Sidebar Login
with st.sidebar:
    st.header("🔐 ProStocks Login")
    with st.form("ProStocksLoginForm"):
        uid = st.text_input("User ID", value=DEFAULT_UID)
        pwd = st.text_input("Password", type="password", value=DEFAULT_PWD)
        factor2 = st.text_input("PAN / DOB (DD-MM-YYYY)", value=DEFAULT_FACTOR2)
        vc = st.text_input("Vendor Code", value=DEFAULT_VC or uid)
        api_key = st.text_input("API Key", type="password", value=DEFAULT_API_KEY)
        imei = st.text_input("MAC Address", value=DEFAULT_MAC)
        base_url = st.text_input("Base URL", value=DEFAULT_BASE_URL)
        apkversion = st.text_input("APK Version", value=DEFAULT_APK_VERSION)

        submitted = st.form_submit_button("🔐 Login")

        if submitted:
            try:
                ps_api = ProStocksAPI(uid, pwd, factor2, vc, api_key, imei, base_url, apkversion)
                success, msg = ps_api.login()
                if success:
                    st.session_state["ps_api"] = ps_api
                    st.success("✅ Login Successful")
                    st.rerun()
                else:
                    st.error(f"❌ Login failed: {msg}")
            except Exception as e:
                st.error(f"❌ Exception: {e}")

# 📊 TABS
tab1, tab2, tab3 = st.tabs(["⚙️ Trade Controls", "📊 Dashboard", "📈 Market Data"])
# === Load saved settings at app start
if "settings_loaded" not in st.session_state:
    st.session_state.update(load_settings())
    st.session_state["settings_loaded"] = True

# === Step 0: Trade Control Panel (Tab 1) ===
with tab1:
    st.subheader("⚙️ Step 0: Trading Control Panel")

    master = st.toggle("✅ Master Auto Buy + Sell", value=st.session_state.get("master_auto", True))
    auto_buy = st.toggle("▶️ Auto Buy Enabled", value=st.session_state.get("auto_buy", True))
    auto_sell = st.toggle("🔽 Auto Sell Enabled", value=st.session_state.get("auto_sell", True))

    # Update session and save to file
    st.session_state["master_auto"] = master
    st.session_state["auto_buy"] = auto_buy
    st.session_state["auto_sell"] = auto_sell

    # Save to file after change
    save_settings({
        "master_auto": master,
        "auto_buy": auto_buy,
        "auto_sell": auto_sell
    })


# 📈 === Tab 3: Market Data ===
with tab3:
    st.subheader("📈 Live Market Table – Approved Stocks")
    market_data = []

    for symbol in APPROVED_STOCK_LIST:
        try:
            full_symbol = f"{symbol}-EQ"

            if "ps_api" in st.session_state:
                ps_api = st.session_state["ps_api"]
                ltp = ps_api.get_ltp("NSE", full_symbol)
                candles = ps_api.get_time_price_series("NSE", full_symbol, "5minute", "1")
                latest = candles[-1] if candles else {}
            else:
                ltp = "🔒 Login required"
                latest = {}

            market_data.append({
                "Symbol": symbol,
                "LTP (₹)": ltp,
                "Open": latest.get("open"),
                "High": latest.get("high"),
                "Low": latest.get("low"),
                "Close": latest.get("close"),
                "Volume": latest.get("volume")
            })

        except Exception as e:
            market_data.append({
                "Symbol": symbol,
                "LTP (₹)": "⚠️ Error",
                "Open": None,
                "High": None,
                "Low": None,
                "Close": None,
                "Volume": None
            })

    df_market = pd.DataFrame(market_data)
    st.dataframe(df_market, use_container_width=True)

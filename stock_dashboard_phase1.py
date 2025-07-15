
# stock_dashboard_clean.py

import streamlit as st
import os
from dotenv import load_dotenv
from prostocks_connector import ProStocksAPI
import pandas as pd

# Load credentials
load_dotenv()
# ✅ Approved stock list
APPROVED_STOCK_LIST = [
    "LTFOODS", "HSCL", "REDINGTON", "FIRSTCRY", "GSPL", "ATGL", "HEG", "RAYMOND", "GUJGASLTD",
    "TRITURBINE", "ADANIPOWER", "ELECON", "JIOFIN", "USHAMART", "INDIACEM", "HINDPETRO", "SONATSOFTW",
    "HONASA", "BSOFT", "KARURVYSYA", "SYRMA", "IGIL", "GRAPHITE", "BLS", "IGL", "NATIONALUM",
    "ENGINERSIN", "MANAPPURAM", "SWIGGY", "GODIGIT", "DBREALTY", "NAVA", "TRIVENI", "SWSOLAR", "BERGEPAINT",
    "JINDALSAW", "ABCAPITAL", "ANANTRAJ", "GMDCLTD", "PETRONET", "VEDL", "HINDCOPPER", "NYKAA", "RBLBANK",
    "AKUMS", "HUDCO", "STARHEALTH", "EIHOTEL", "SCI", "OIL", "CGPOWER", "NLCINDIA", "LTF", "AWL", "RVNL",
    "SUMICHEM", "KANSAINER", "HBLENGINE", "CHENNPETRO", "LICHSGFIN", "ELGIEQUIP", "KALYANKJIL", "PRAJIND",
    "KIMS", "INDUSTOWER", "INDIANB", "VGUARD", "JSL", "AMBUJACEM", "TARIL", "GAIL", "RHIM", "IRCON", "ASTERDM",
    "BANKBARODA", "POONAWALLA", "M&MFIN", "KNRCON", "DELHIVERY", "RKFORGE", "POWERGRID", "JSWENERGY", "INDGN",
    "PCBL", "IEX", "CASTROLIND", "IIFL", "SWANENERGY", "JKTYRE", "JYOTHYLAB", "CUB", "NIACL", "RAILTEL",
    "ETERNAL", "GPIL", "HAPPSTMNDS", "GNFC", "RECLTD", "PNCINFRA", "WIPRO", "BPCL", "NTPC", "JSWINFRA", "PFC",
    "SYNGENE", "JWL", "BANDHANBNK", "BHEL", "CGCL", "INOXWIND", "RITES", "FSL", "MINDACORP", "LATENTVIEW",
    "AADHARHFC", "GICRE", "AFCONS", "CROMPTON", "FEDERALBNK", "BEL", "PPLPHARMA", "ONGC", "JBMA", "UPL", "NCC",
    "CAMPUS", "GRANULES", "APOLLOTYRE", "VBL", "SARDAEN", "FINPIPE", "SONACOMS", "BIOCON", "AARTIIND",
    "ACMESOLAR", "BALRAMCHIN", "EXIDEIND", "TATAPOWER", "SHRIRAMFIN", "DEVYANI", "CHAMBLFERT", "HINDZINC",
    "COALINDIA", "DABUR", "SAPPHIRE", "ICICIPRULI", "HINDALCO", "TATAMOTORS", "ASHOKLEY", "CESC", "ITC"
]

DEFAULT_UID = os.getenv("PROSTOCKS_USER_ID", "")
DEFAULT_PWD = os.getenv("PROSTOCKS_PASSWORD", "")
DEFAULT_FACTOR2 = os.getenv("PROSTOCKS_FACTOR2", "")
DEFAULT_VC = os.getenv("PROSTOCKS_VENDOR_CODE", "")
DEFAULT_API_KEY = os.getenv("PROSTOCKS_API_KEY", "")
DEFAULT_MAC = os.getenv("PROSTOCKS_MAC", "MAC123456")
DEFAULT_BASE_URL = os.getenv("PROSTOCKS_BASE_URL", "https://starapi.prostocks.com/NorenWClientTP")
DEFAULT_APK_VERSION = os.getenv("PROSTOCKS_APK_VERSION", "1.0.0")

# Sidebar Login UI
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

              
# Main content (tabs)
if "ps_api" in st.session_state:
    ps_api = st.session_state["ps_api"]

    tab1, tab2 = st.tabs(["📊 Dashboard", "📈 Market Data"])

    # 🚀 Tab 2: Market Data (LTP + Intraday)
    with tab2:
        st.subheader("📈 Live Market Table – Approved Stocks")

        market_data = []

        for symbol in APPROVED_STOCK_LIST:
            try:
                full_symbol = f"{symbol}-EQ"
                ltp = ps_api.get_ltp("NSE", full_symbol)
                candles = ps_api.get_time_price_series("NSE", full_symbol, "5minute", "1")
                latest = candles[-1] if candles else {}

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

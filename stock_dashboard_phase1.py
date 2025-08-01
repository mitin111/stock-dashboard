
# main_app.py

import streamlit as st
import pandas as pd
from prostocks_connector import ProStocksAPI
from dashboard_logic import load_settings, save_settings, load_credentials
from datetime import datetime

# === Page Layout ===
st.set_page_config(page_title="Auto Intraday Trading", layout="wide")
st.title("📈 Automated Intraday Trading System")

# === Load Settings (once) ===
if "settings_loaded" not in st.session_state:
    st.session_state.update(load_settings())
    st.session_state["settings_loaded"] = True

# === Load ProStocks credentials from .env or JSON
creds = load_credentials()

# === Approved Stock List ===
original_symbols = [
    "LTFOODS", "HSCL", "REDINGTON", "FIRSTCRY", "GSPL", "ATGL",
    "HEG", "RAYMOND", "GUJGASLTD", "TRITURBINE", "ADANIPOWER", "ELECON",
    "JIOFIN", "USHAMART", "INDIACEM", "HINDPETRO", "SONATSOFTW"
]
APPROVED_STOCK_LIST = [symbol + "-EQ" for symbol in original_symbols]

# === Token Mappings for Approved Stocks ===
matched_tokens = {
    "REDINGTON": "14255",
    "HEG": "1336",
    "ELECON": "13643",
    "USHAMART": "8840",
    "HINDPETRO": "1406",
    "SONATSOFTW": "6596"
}

def get_token(symbol):
    base_symbol = symbol.replace("-EQ", "")
    return matched_tokens.get(base_symbol)

# === Sidebar Login Form ===
with st.sidebar:
    st.header("🔐 ProStocks OTP Login")

    if st.button("📩 Send OTP"):
        temp_api = ProStocksAPI(
            userid=creds["uid"],
            password_plain=creds["pwd"],
            vc=creds["vc"],
            api_key=creds["api_key"],
            imei=creds["imei"],
            base_url=creds["base_url"],
            apkversion=creds["apkversion"]
        )
        success, msg = temp_api.login("")  # empty OTP triggers OTP sending
        if not success:
            st.info(f"ℹ️ OTP Trigger Response: {msg}")
        else:
            st.success("✅ OTP has been sent to your registered Email/SMS.")

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
                    userid=uid,
                    password_plain=pwd,
                    vc=vc,
                    api_key=api_key,
                    imei=imei,
                    base_url=base_url,
                    apkversion=apkversion
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

# === Logout Button ===
if "ps_api" in st.session_state:
    st.sidebar.markdown("---")
    if st.sidebar.button("🔓 Logout"):
        del st.session_state["ps_api"]
        st.success("✅ Logged out successfully")
        st.rerun()

# === Tabs ===
tab1, tab2, tab3, tab4 = st.tabs([
    "⚙️ Trade Controls",
    "📊 Dashboard",
    "📈 Market Data",
    "📐 Indicator Settings"
])

# === Tab 1: Trade Controls ===
with tab1:
    st.subheader("⚙️ Step 0: Trading Control Panel")

    master = st.toggle("✅ Master Auto Buy + Sell", value=st.session_state.get("master_auto", True), key="master_toggle")
    auto_buy = st.toggle("▶️ Auto Buy Enabled", value=st.session_state.get("auto_buy", True), key="auto_buy_toggle")
    auto_sell = st.toggle("🔽 Auto Sell Enabled", value=st.session_state.get("auto_sell", True), key="auto_sell_toggle")

    st.markdown("#### ⏱️ Trading Timings")

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

# === Tab 2: Placeholder Dashboard ===
with tab2:
    st.subheader("📊 Dashboard")
    st.info("Coming soon...")

# === Tab 3: Live Market Data ===
with tab3:
    st.subheader("📈 Live Market Table – Approved Stocks")

    if "ps_api" not in st.session_state:
        st.warning("🔒 Please login to ProStocks to load market data.")
    else:
        market_data = []
        ps_api = st.session_state["ps_api"]

        for symbol in APPROVED_STOCK_LIST:
            try:
                ltp = ps_api.get_ltp(symbol)
                quote = ps_api.get_quotes(symbol=symbol, exchange="NSE")

                market_data.append({
                    "Symbol": symbol,
                    "LTP (₹)": ltp,
                    "Open": quote.get("op") if quote else None,
                    "High": quote.get("hp") if quote else None,
                    "Low": quote.get("lp") if quote else None,
                    "Close": quote.get("c") if quote else None,
                    "Volume": quote.get("v") if quote else None
                })
            except Exception as e:
                st.error(f"❌ Error for {symbol}: {e}")
                market_data.append({
                    "Symbol": symbol,
                    "LTP (₹)": "⚠️ Error",
                    "Open": None, "High": None, "Low": None,
                    "Close": None, "Volume": None
                })

        df_market = pd.DataFrame(market_data)
        st.dataframe(df_market, use_container_width=True)

# === Tab 4: Indicator Settings ===
with tab4:
    st.info("📐 Indicator settings section coming soon...")

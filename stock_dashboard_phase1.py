
# main_app.py

import streamlit as st
import pandas as pd
from prostocks_connector import ProStocksAPI
from dashboard_logic import load_settings, save_settings, load_credentials
from datetime import datetime, time

# 🧱 Page Layout
st.set_page_config(page_title="Auto Intraday Trading", layout="wide")
st.title("📈 Automated Intraday Trading System")

# === Load and Apply Settings (only once)
if "settings_loaded" not in st.session_state:
    st.session_state.update(load_settings())
    st.session_state["settings_loaded"] = True

# === Load Credentials from .env
creds = load_credentials()

# ✅ Approved stock list
original_symbols = [
    "LTFOODS", "HSCL", "REDINGTON", "FIRSTCRY", "GSPL", "ATGL",
    "HEG", "RAYMOND", "GUJGASLTD", "TRITURBINE", "ADANIPOWER", "ELECON",
    "JIOFIN", "USHAMART", "INDIACEM", "HINDPETRO", "SONATSOFTW"
]

APPROVED_STOCK_LIST = [symbol + "-EQ" for symbol in original_symbols]

# 🔐 Sidebar Login
with st.sidebar:
    st.header("🔐 ProStocks Login")
    with st.form("ProStocksLoginForm"):
        uid = st.text_input("User ID", value=creds["uid"])
        pwd = st.text_input("Password", type="password", value=creds["pwd"])
        factor2 = st.text_input("PAN / DOB", value=creds["factor2"])
        vc = st.text_input("Vendor Code", value=creds["vc"] or uid)
        api_key = st.text_input("API Key", type="password", value=creds["api_key"])
        imei = st.text_input("MAC Address", value=creds["imei"])
        base_url = st.text_input("Base URL", value=creds["base_url"])
        apkversion = st.text_input("APK Version", value=creds["apkversion"])

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

# 🔓 Logout button if already logged in
if "ps_api" in st.session_state:
    st.markdown("---")
    if st.button("🔓 Logout"):
        del st.session_state["ps_api"]
        st.success("✅ Logged out successfully")
        st.rerun()

# === Tabs Layout
tab1, tab2, tab3, tab4 = st.tabs([
    "⚙️ Trade Controls", 
    "📊 Dashboard", 
    "📈 Market Data",
    "📐 Indicator Settings & View"
])


# === Tab 1: Trade Control Panel ===
with tab1:
    st.subheader("⚙️ Step 0: Trading Control Panel")

    # ✅ Unique keys for toggles
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

    # Save to file (Streamlit already has correct session state due to widget keys)
    save_settings({
        "master_auto": master,
        "auto_buy": auto_buy,
        "auto_sell": auto_sell,
        "trading_start": trading_start.strftime("%H:%M"),
        "trading_end": trading_end.strftime("%H:%M"),
        "cutoff_time": cutoff_time.strftime("%H:%M"),
        "auto_exit_time": auto_exit_time.strftime("%H:%M")
    })


# === Tab 3: Market Data ===
with tab3:
    st.subheader("📈 Live Market Table – Approved Stocks")

    if "ps_api" not in st.session_state:
        st.warning("🔒 Please login to ProStocks to load market data.")
    else:
        market_data = []
        ps_api = st.session_state["ps_api"]

        for symbol in APPROVED_STOCK_LIST:
            try:
                full_symbol = f"{symbol}-EQ"
                ltp = ps_api.get_ltp(full_symbol)
                quote = ps_api.get_quotes(symbol=full_symbol, exchange="NSE")

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



# === Tab 4 continued...

sample_token = "2885"  # 🔁 Use ProStocks token for RELIANCE (example)
if "ps_api" in st.session_state:
    ps_api = st.session_state["ps_api"]
    candles = ps_api.get_candles(sample_token, interval="5", days=1)

    if candles:
        df = pd.DataFrame(candles, columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"])
        df["Timestamp"] = pd.to_datetime(df["Timestamp"])  # Ensure correct time format

        # 🚫 Temporarily disabled MACD logic
# macd_df = calculate_macd(
#     df,
#     fast_length=macd_fast,
#     slow_length=macd_slow,
#     signal_length=macd_signal,
#     src_col=macd_source,
#     ma_type_macd=macd_ma_type,
#     ma_type_signal=macd_ma_type
# )

# macd_hist = macd_df["Histogram"].iloc[-1]
# st.write(f"**MACD:** {round(macd_df['MACD'].iloc[-1], 3)}")
# st.write(f"**Signal:** {round(macd_df['Signal'].iloc[-1], 3)}")
# st.write(f"**Histogram:** {round(macd_hist, 3)}")

    else:
        st.warning("⚠️ No data available from ProStocks for MACD.")
else:
    st.warning("🔒 Login to ProStocks to view MACD output.")

from dashboard_logic import place_test_order
from prostocks_connector import login_ps  # make sure you’re using the right login module

# === Place test order button ===
with st.expander("🔧 Test Order Placement (UAT Only)"):
    if st.button("🚀 Place Test Order on INFY-EQ"):
        try:
            api = login_ps()  # login and get session
            response = place_test_order(api)
            st.success("✅ Order Placed Successfully!")
            st.json(response)
        except Exception as e:
            st.error(f"❌ Order Placement Failed: {e}")


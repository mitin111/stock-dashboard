
import os
import logging
import streamlit as st
from dotenv import load_dotenv
from prostocks_connector import login_ps
from intraday_trading_engine import TradingEngine

# ✅ Basic setup
st.set_page_config(page_title="📈 Intraday Stock Dashboard", layout="wide")
logging.basicConfig(level=logging.DEBUG)
load_dotenv()
print("📄 app.py started execution")




# ========== LOGIN BLOCK ==========

if "ps_api" not in st.session_state:
    st.title("🔐 Login to ProStocks")

    # Load from environment (Render or .env)
    env_user_id = os.getenv("PROSTOCKS_USER_ID")
    env_password = os.getenv("PROSTOCKS_PASSWORD")
    env_totp = os.getenv("PROSTOCKS_FACTOR2")

    env_api_key = os.getenv("PROSTOCKS_API_KEY")

    # 🧠 Show login form (default values filled if in env)
    with st.form("login_form"):
        st.markdown("**🔑 Enter your ProStocks API credentials:**")
        user_id = st.text_input("User ID", value=env_user_id or "")
        password = st.text_input("Password", type="password", value=env_password or "")
        totp_secret = st.text_input("TOTP Secret", value=env_totp or "")
        api_key = st.text_input("API Key", value=env_api_key or "")
        submitted = st.form_submit_button("Login")

    if submitted:
        st.warning("🚧 Login button pressed - starting login...")
        logging.debug("🚀 login_ps() function started")

        # Call login with these inputs
        with st.spinner("🔄 Logging in..."):
            ps_api = login_ps(user_id, password, totp_secret, api_key)

        if ps_api:
            st.session_state["ps_api"] = ps_api
            st.success("✅ Login successful! Reloading...")
            st.experimental_rerun()
        else:
            st.error("❌ Login failed. Please check your credentials.")
            st.stop()
    else:
        # ⚠️ STOP page until form is submitted
        st.warning("🔒 Please login to continue.")
        st.stop()





# ========== DASHBOARD BEGINS AFTER LOGIN ==========

class Dashboard:
    def __init__(self):
        st.sidebar.title("⚙️ Trading Controls")
        self.auto_buy = st.sidebar.checkbox("Auto Buy", value=False)
        self.auto_sell = st.sidebar.checkbox("Auto Sell", value=False)
        self.master_auto = st.sidebar.checkbox("Master Auto Mode", value=False)

    def log_trade(self, symbol, side, price, qty, sl, tgt, time):
        st.success(f"{side} {symbol} @ ₹{price} | Qty: {qty} | SL: ₹{sl} | Target: ₹{tgt} | Time: {time}")

    def close_position(self, symbol, position):
        st.warning(f"Auto-exited {symbol} ({position['side']}) @ {position['entry_price']}")

    def update_visuals(self, positions, indicators):
        st.subheader("📊 Active Positions")
        st.write(positions)

# 🎯 Main UI Title
st.title("📈 Intraday Trading Dashboard")

# 🧠 Initialize engine
dashboard = Dashboard()
engine = TradingEngine(dashboard, st.session_state["ps_api"])

# ✅ Simulated input example (you will replace this with real logic later)
stock_data = {
    "symbol": "LTFOODS",
    "price": 190,
    "y_close": 185,
    "open": 186,
    "indicators": {
        "atr_trail": "Buy",
        "tkp_trm": "Buy",
        "macd_hist": 0.5,
        "above_pac": True,
        "volatility": 2.3,
        "min_vol_required": 2.0,
        "pac_band_lower": 185,
        "pac_band_upper": 194
    },
    "qcfg": {"Q1": 100, "Q2": 80, "Q3": 60, "Q4": 40, "Q5": 30, "Q6": 20},
    "time": "09:30",
    "balance": 50000
}

# 🚀 Trigger trade engine if enabled
if dashboard.master_auto:
    engine.process_trade(**stock_data)

import streamlit as st
from prostocks_connector import login_ps
from intraday_trading_engine import TradingEngine

st.set_page_config(page_title="📈 Intraday Stock Dashboard", layout="wide")
print("📄 app.py started execution")

# ========== LOGIN BLOCK ==========
if "ps_api" not in st.session_state:
    st.title("🔐 Login to ProStocks")

    with st.form("login_form"):
        client_id = st.text_input("Client ID", value="", placeholder="Enter your ProStocks ID")
        password = st.text_input("Password", type="password", placeholder="••••••••")
        factor2 = st.text_input("PAN / DOB (DD-MM-YYYY)", placeholder="ABCDE1234F")
        submit_btn = st.form_submit_button("Login")

    if submit_btn:
        with st.spinner("Logging in..."):
            ps_api = login_ps(client_id, password, factor2)

        if ps_api:
            st.session_state["ps_api"] = ps_api
            st.success("✅ Logged in successfully! Please reload.")
            st.experimental_rerun()
        else:
            st.error("❌ Login failed. Please check your credentials.")
    st.stop()  # Halt further execution until login is successful.



# ========== DASHBOARD BEGINS AFTER LOGIN ==========

# Dummy dashboard class
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

st.title("📈 Intraday Trading Dashboard")

dashboard = Dashboard()
engine = TradingEngine(dashboard, st.session_state["ps_api"])


# Example static data to simulate
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

# Only process trades if auto mode is enabled
if dashboard.master_auto:
    engine.process_trade(**stock_data)

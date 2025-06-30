# stock_dashboard_phase2.py

import streamlit as st
from datetime import datetime, timedelta

# --- Dashboard Config ---
st.set_page_config(page_title="📊 Stock Strategy Dashboard - Phase 2", layout="wide")
st.title("📈 Stock Screener & Strategy Control Panel (Phase 2)")

st.markdown("""
Use the panel below to configure your indicator settings, stock quantity, entry/exit rules, and more.
All selections affect strategy logic dynamically.
""")

# --- Control Panel ---
st.sidebar.header("⚙️ Strategy Settings")

# Quantity and Bracket Order
quantity = st.sidebar.number_input("📦 Order Quantity", min_value=1, value=50)
use_bracket = st.sidebar.checkbox("🧩 Use Bracket Orders", value=True)

# Indicator Settings
st.sidebar.subheader("📐 Indicator Parameters")
tsi_long = st.sidebar.slider("TSI Long Length", 5, 50, 25)
tsi_short = st.sidebar.slider("TSI Short Length", 2, 20, 5)
tsi_signal = st.sidebar.slider("TSI Signal Length", 5, 25, 14)
rsi_length = st.sidebar.slider("RSI Length", 2, 20, 5)
rsi_buy = st.sidebar.slider("RSI Buy Level", 40, 70, 50)
rsi_sell = st.sidebar.slider("RSI Sell Level", 30, 60, 50)

# MACD Histogram Settings
st.sidebar.subheader("📊 MACD Histogram")
macd_fast = st.sidebar.slider("MACD Fast Length", 10, 150, 90)
macd_slow = st.sidebar.slider("MACD Slow Length", 20, 300, 210)
macd_signal = st.sidebar.slider("MACD Signal Smoothing", 5, 15, 9)

# PAC EMA Settings
st.sidebar.subheader("📈 PAC Channel")
pac_length = st.sidebar.slider("PAC EMA Length", 10, 55, 34)
use_heikin_ashi = st.sidebar.checkbox("Use Heikin Ashi Candles", value=True)

# ATR Settings
st.sidebar.subheader("📏 ATR Parameters")
atr_fast_len = st.sidebar.slider("Fast ATR Period", 2, 20, 5)
atr_fast_mult = st.sidebar.number_input("Fast ATR Multiplier", value=0.5)
atr_slow_len = st.sidebar.slider("Slow ATR Period", 5, 30, 10)
atr_slow_mult = st.sidebar.number_input("Slow ATR Multiplier", value=3.0)

# Target and Stoploss
st.sidebar.subheader("🎯 Target & Stoploss")
target_pct = st.sidebar.number_input("Target %", value=1.0)
stoploss_source = st.sidebar.selectbox("Stoploss Based On", ["PAC Low EMA", "PAC High EMA"])

# Entry Conditions
st.sidebar.subheader("🚦 Entry Conditions")
entry_condition = st.sidebar.radio("Entry Trigger", ["Cross Fib R2", "Break Fib S2"], index=0)
yhl_condition = st.sidebar.radio("Price vs Y.High/Low", ["Above Y.High", "Below Y.Low"], index=0)
pac_condition = st.sidebar.radio("PAC Filter", ["Trade Above PAC", "Trade Below PAC"], index=0)

# Stock Selection
st.sidebar.subheader("📃 Stock Selection")
user_symbols = st.sidebar.text_area("Enter comma-separated stock symbols:",
    "TATAPOWER.NS,WIPRO.NS")
symbol_list = [sym.strip().upper() for sym in user_symbols.split(",") if sym.strip() != ""]

# Summary Panel
st.subheader("🧾 Configuration Summary")
st.markdown(f"""
- **Symbols Scanning:** `{symbol_list}`
- **Order Quantity:** `{quantity}` | **Bracket Order:** `{use_bracket}`
- **TSI:** Long = `{tsi_long}`, Short = `{tsi_short}`, Signal = `{tsi_signal}`
- **RSI:** Length = `{rsi_length}`, Buy = `{rsi_buy}`, Sell = `{rsi_sell}`
- **MACD Histogram:** Fast = `{macd_fast}`, Slow = `{macd_slow}`, Signal = `{macd_signal}`
- **PAC Length:** `{pac_length}` | **Heikin Ashi:** `{use_heikin_ashi}`
- **ATR Fast:** {atr_fast_len} × {atr_fast_mult} | **ATR Slow:** {atr_slow_len} × {atr_slow_mult}
- **Target:** `{target_pct}%` | **Stoploss on:** `{stoploss_source}`
- **Entry:** `{entry_condition}` | **YHL Check:** `{yhl_condition}` | **PAC Filter:** `{pac_condition}`
""")

st.info("✅ Settings above will be used by the strategy logic for screening & signal generation.")

# Placeholder for results / logic
st.subheader("🔍 Strategy Logic Placeholder")
st.write("➡️ In next phase: Integrate with Pine Script screener & backend for real-time signal dashboard.")

# stock_dashboard_phase1.py

import os
import streamlit as st

# correct port binding
if "PORT" in os.environ:
    os.environ["STREAMLIT_SERVER_PORT"] = os.environ["PORT"]
    os.environ["STREAMLIT_SERVER_ADDRESS"] = "0.0.0.0"

# first UI command
st.set_page_config(page_title="Auto Intraday Trading", layout="wide")

# health check (simple and safe)
# ✅ HEALTH CHECK (no crash, no blink)
params = st.query_params  # <-- new Streamlit API

if params.get("healthz") == ["1"]:
    st.text("ok")
    st.stop()

import pandas as pd
from prostocks_connector import ProStocksAPI
from dashboard_logic import load_settings, save_settings, load_credentials
from datetime import datetime, timedelta
import calendar
import time
import json
import requests
from urllib.parse import urlencode
from datetime import timezone
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pytz

try:
    import websocket
except:
    websocket = None

# ✅ Normalize ProStocks login responses
def resp_to_dict(resp):
    """Normalize login response: support both dict and tuple formats."""
    if isinstance(resp, dict):
        return resp
    if isinstance(resp, (tuple, list)) and len(resp) == 2:
        success, msg = resp
        return {
            "stat": "Ok" if success else "Not_Ok",
            "emsg": None if success else msg
        }
    return {"stat": "Not_Ok", "emsg": "Unexpected response format"}


# === Page Layout ===
st.title("📈 Automated Intraday Trading System")

# === Load Settings (once) ===
if "settings_loaded" not in st.session_state:
    st.session_state.update(load_settings())
    st.session_state["settings_loaded"] = True

# === Load Credentials ===
creds = load_credentials()

# === Sidebar Login ===
# === Sidebar Login ===
with st.sidebar:
    st.header("🔐 ProStocks OTP Login")

    # --- OTP Button ---
    if st.button("📩 Send OTP"):
        temp_api = ProStocksAPI(**creds)
        resp = resp_to_dict(temp_api.login(""))
        if resp.get("stat") == "Ok":
            st.success("✅ OTP Sent — Check SMS/Email")
        else:
            st.warning(f"⚠️ {resp.get('emsg', 'Unable to send OTP')}")

    # --- Login Form ---
    with st.form("LoginForm"):
        uid = st.text_input("User ID", value=creds["uid"])
        pwd = st.text_input("Password", type="password", value=creds["pwd"])
        factor2 = st.text_input("OTP from SMS/Email")
        vc = st.text_input("Vendor Code", value=creds["vc"] or uid)
        api_key = st.text_input("API Key", type="password", value=creds["api_key"])
        imei = st.text_input("MAC Address", value=creds["imei"])
        base_url = st.text_input(
            "Base URL",
            value=os.getenv("PROSTOCKS_BASE_URL", "https://starapi.prostocks.com/NorenWClientTP")
        )
        apkversion = st.text_input("APK Version", value=creds["apkversion"])

        submitted = st.form_submit_button("🔐 Login")
        if submitted:
            try:
                ps_api = ProStocksAPI(
                    userid=uid, password_plain=pwd, vc=vc,
                    api_key=api_key, imei=imei,
                    base_url=base_url, apkversion=apkversion
                )

                login_resp = resp_to_dict(ps_api.login(factor2))

                if login_resp.get("stat") == "Ok":
                    st.session_state["ps_api"] = ps_api
                    st.session_state["logged_in"] = True
                    st.session_state.jKey = ps_api.session_token
                    st.session_state["chart_open"] = False   # ✅ Prevent auto-open

                    st.success("✅ Login Successful — Now open Tab 5 and Click 'Open Chart'")

                else:
                    st.error(f"❌ Login failed: {login_resp.get('emsg', 'Unknown error')}")

            except Exception as e:
                st.error(f"❌ Exception: {e}")

    # --- Logout ---
    if st.button("🔓 Logout"):
        st.session_state.pop("ps_api", None)
        st.session_state["logged_in"] = False
        st.success("✅ Logged out successfully")


# === Tabs ===
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "⚙️ Trade Controls",
    "📊 Dashboard",
    "📈 Market Data",
    "📀 Indicator Settings",
    "📉 Strategy Engine"
])

# === Tab 1: Trade Controls ===
with tab1:
    st.subheader("⚙️ Step 0: Trading Control Panel")
    master = st.toggle("✅ Master Auto Buy + Sell", st.session_state.get("master_auto", True), key="master_toggle")
    auto_buy = st.toggle("▶️ Auto Buy Enabled", st.session_state.get("auto_buy", True), key="auto_buy_toggle")
    auto_sell = st.toggle("🔽 Auto Sell Enabled", st.session_state.get("auto_sell", True), key="auto_sell_toggle")

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

import numpy as np
import json

# === Tab 2: Dashboard ===
with tab2:
    st.subheader("📊 Dashboard")

    # ✅ HARD STOP — prevents Connecting-Blink
    if not st.session_state.get("logged_in", False):
        st.info("🔐 Please login first to view Dashboard.")
        st.stop()

    ps_api = st.session_state.ps_api

    # --- Refresh button safely updates cache ---
    if st.button("🔄 Refresh Order/Trade Book"):
        try:
            st.session_state._order_book = ps_api.order_book()
            st.session_state._trade_book = ps_api.trade_book()
        except Exception as e:
            st.warning(f"⚠️ Could not refresh books: {e}")

    # --- Get cached books (never call API automatically) ---
    ob_list = st.session_state.get("_order_book", [])
    tb_list = st.session_state.get("_trade_book", [])

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📑 Order Book")
        if ob_list:
            df_ob = pd.DataFrame(ob_list)
            show_cols = ["norenordno","exch","tsym","trantype","qty","prc","prctyp","status","rejreason","avgprc","ordenttm","norentm"]
            df_ob = df_ob.reindex(columns=show_cols, fill_value="")
            st.dataframe(df_ob, use_container_width=True, height=400)
        else:
            st.info("📭 No orders yet.")

    with col2:
        st.markdown("### 📑 Trade Book")
        if tb_list:
            df_tb = pd.DataFrame(tb_list)
            show_cols = ["norenordno","exch","tsym","trantype","fillshares","avgprc","status","norentm"]
            df_tb = df_tb.reindex(columns=show_cols, fill_value="")
            st.dataframe(df_tb, use_container_width=True, height=400)
        else:
            st.info("📭 No trades yet.")


# === Tab 3: Market Data ===
with tab3:
    st.subheader("📈 Live Market Table – Watchlist Viewer")

    # ✅ HARD STOP: Market Data must NOT run before login (blink fix)
    if not st.session_state.get("logged_in", False):
        st.info("🔐 Please login to view live watchlist data.")
        st.stop()   # <--- THIS FIXES THE BLINK COMPLETELY

    ps_api = st.session_state["ps_api"]

    try:
        wl_resp = ps_api.get_watchlists()
    except Exception as e:
        st.warning(f"⚠️ Could not fetch watchlists: {e}")
        st.stop()

    if wl_resp.get("stat") != "Ok":
        st.warning(wl_resp.get("emsg", "Could not fetch watchlists."))
        st.stop()

    raw_watchlists = wl_resp["values"]
    watchlists = sorted(raw_watchlists, key=int)
    wl_labels = [f"Watchlist {wl}" for wl in watchlists]

    selected_label = st.selectbox("📁 Choose Watchlist", wl_labels)
    selected_wl = dict(zip(wl_labels, watchlists))[selected_label]

    st.session_state.all_watchlists = watchlists
    st.session_state.selected_watchlist = selected_wl

    wl_data = ps_api.get_watchlist(selected_wl)
    if wl_data.get("stat") == "Ok":
        df = pd.DataFrame(wl_data["values"])
        st.write(f"📦 {len(df)} scrips in watchlist '{selected_wl}'")
        st.dataframe(df if not df.empty else pd.DataFrame())

        symbols_with_tokens = []
        for s in wl_data["values"]:
            token = s.get("token", "")
            if token:
                symbols_with_tokens.append({"tsym": s["tsym"], "exch": s["exch"], "token": token})
        st.session_state["symbols"] = symbols_with_tokens
        st.success(f"✅ {len(symbols_with_tokens)} symbols ready for WebSocket/AutoTrader")
    else:
        st.warning(wl_data.get("emsg", "Failed to load watchlist."))


# === Tab 4: Indicator Settings ===
with tab4:
    from tab4_auto_trader import render_tab4
    from tkp_trm_chart import render_trm_settings_once

    st.subheader("📀 Indicator & TRM Settings")

    # ✅ If not logged in → do NOT load tab4 UI
    if not st.session_state.get("logged_in", False):
        st.info("🔐 Please login first to configure Auto Trader settings.")
        st.stop()

    # ✅ Ensure expander flag initialized BEFORE calling UI builder
    if "trm_settings_expander_rendered" not in st.session_state:
        st.session_state["trm_settings_expander_rendered"] = False

    # ✅ Now safe to load tab4
    render_tab4(require_session_settings=True, allow_file_fallback=False)

    st.markdown("---")
    render_trm_settings_once()




























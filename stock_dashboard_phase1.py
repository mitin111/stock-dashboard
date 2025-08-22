
# main_app_live.py
import streamlit as st
import pandas as pd
from prostocks_connector import ProStocksAPI
from dashboard_logic import load_settings, save_settings, load_credentials
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import threading
from streamlit_autorefresh import st_autorefresh

# === Page Layout ===
st.set_page_config(page_title="Auto Intraday Trading", layout="wide")
st.title("📈 Automated Intraday Trading System")

# === Load Settings (once) ===
if "settings_loaded" not in st.session_state:
    st.session_state.update(load_settings())
    st.session_state["settings_loaded"] = True

# === Load Credentials ===
creds = load_credentials()

# === Sidebar Login ===
with st.sidebar:
    st.header("🔐 ProStocks OTP Login")
    if st.button("📩 Send OTP"):
        temp_api = ProStocksAPI(**creds)
        success, msg = temp_api.login("")
        st.success("✅ OTP Sent") if success else st.info(f"ℹ️ {msg}")

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
                    userid=uid, password_plain=pwd, vc=vc,
                    api_key=api_key, imei=imei,
                    base_url=base_url, apkversion=apkversion
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

if "ps_api" in st.session_state:
    if st.sidebar.button("🔓 Logout"):
        del st.session_state["ps_api"]
        st.success("✅ Logged out successfully")
        st.rerun()

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

# === Tab 2: Dashboard ===
with tab2:
    st.subheader("📊 Dashboard")
    st.info("Coming soon...")

# === Tab 3: Market Data ===
with tab3:
    st.subheader("📈 Live Market Table – Watchlist Viewer")

    if "ps_api" in st.session_state:
        ps_api = st.session_state["ps_api"]
        wl_resp = ps_api.get_watchlists()
        if wl_resp.get("stat") == "Ok":
            raw_watchlists = wl_resp["values"]
            watchlists = sorted(raw_watchlists, key=int)
            wl_labels = [f"Watchlist {wl}" for wl in watchlists]
            selected_label = st.selectbox("📁 Choose Watchlist", wl_labels)
            selected_wl = dict(zip(wl_labels, watchlists))[selected_label]

            wl_data = ps_api.get_watchlist(selected_wl)
            if wl_data.get("stat") == "Ok":
                df = pd.DataFrame(wl_data["values"])
                st.write(f"📦 {len(df)} scrips in watchlist '{selected_wl}'")
                st.dataframe(df if not df.empty else pd.DataFrame())
            else:
                st.warning(wl_data.get("emsg", "Failed to load watchlist."))
        else:
            st.warning(wl_resp.get("emsg", "Could not fetch watchlists."))
    else:
        st.info("ℹ️ Please login to view live watchlist data.")

# === Tab 4: Indicator Settings ===
with tab4:
    st.info("📀 Indicator settings section coming soon...")

# === Helper Functions ===
chart_container = st.empty()

def ensure_datetime(df):
    if "datetime" not in df.columns:
        for cand_col in ["time", "date", "datetime"]:
            if cand_col in df.columns:
                df = df.rename(columns={cand_col: "datetime"})
                break
    if "datetime" not in df.columns:
        return df
    if pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        return df

    dt = pd.to_datetime(df["datetime"], errors="coerce")
    df["datetime"] = dt
    df = df.dropna(subset=["datetime"])
    return df

def get_col(df, *names):
    for n in names:
        if n in df.columns:
            return df[n]
    return None

def plot_tpseries_candles(df, symbol):
    if df.empty:
        return None

    df = df.drop_duplicates(subset=['datetime']).sort_values("datetime")
    df = df[(df['datetime'].dt.time >= pd.to_datetime("09:15").time()) &
            (df['datetime'].dt.time <= pd.to_datetime("15:30").time())]

    fig = make_subplots(rows=1, cols=1, shared_xaxes=True)
    fig.add_trace(go.Candlestick(
        x=df['datetime'],
        open=get_col(df, 'open', 'Open'),
        high=get_col(df, 'high', 'High'),
        low=get_col(df, 'low', 'Low'),
        close=get_col(df, 'close', 'Close'),
        increasing_line_color='#26a69a',
        decreasing_line_color='#ef5350',
        name='Price'
    ))

    # Layout settings for scroll & zoom
    fig.update_layout(
        xaxis_rangeslider_visible=False,  # hide slider
        dragmode='pan',                  # enable scroll
        hovermode='x unified',
        showlegend=False,
        template="plotly_dark",
        height=700,
        margin=dict(l=50, r=50, t=50, b=50),
        plot_bgcolor='black',
        paper_bgcolor='black',
        font=dict(color='white'),
    )

    # Grid lines
    fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='gray')
    fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor='gray', fixedrange=False)

    # Hide weekends & after-hours
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),
            dict(bounds=[15.5, 9.25], pattern="hour")
        ]
    )

    # "Go to Latest" button
    fig.update_layout(
        updatemenus=[dict(
            type="buttons",
            direction="left",
            x=1,
            y=1.15,
            buttons=[
                dict(
                    label="Go to Latest",
                    method="relayout",
                    args=[{"xaxis.range": [df['datetime'].iloc[-50], df['datetime'].iloc[-1]]}]
                )
            ]
        )],
        title=f"{symbol} - TradingView-style Chart"
    )

    return fig

# === TPSeries Fetch Function ===
def fetch_full_tpseries(api, exch, token, interval, days=60):
    final_df = pd.DataFrame()
    ist_offset = timedelta(hours=5, minutes=30)
    today_ist = datetime.utcnow() + ist_offset
    end_dt = today_ist
    start_dt = end_dt - timedelta(days=days)
    current_day = start_dt
    while current_day <= end_dt:
        day_start = current_day.replace(hour=9, minute=15)
        day_end = current_day.replace(hour=15, minute=30)
        st_epoch = int((day_start - ist_offset).timestamp())
        et_epoch = int((day_end - ist_offset).timestamp())
        resp = api.get_tpseries(exch, token, interval, st_epoch, et_epoch)
        if resp.get("stat") == "Ok" and "values" in resp:
            chunk_df = pd.DataFrame(resp["values"])
            chunk_df["datetime"] = pd.to_datetime(chunk_df["time"], unit="s", utc=True) + ist_offset
            final_df = pd.concat([final_df, chunk_df])
        current_day += timedelta(days=1)
        time.sleep(0.3)
    final_df.sort_values("datetime", inplace=True)
    return final_df

import streamlit as st
import threading, time, queue
import pandas as pd
from datetime import datetime

# === Tab 5: Strategy Engine ===
with tab5:
    st.subheader("📡 Live WebSocket Candles + TPSeries")

    # ---------------- Session state defaults ----------------
    if "ticks" not in st.session_state:
        st.session_state.ticks = {}
    if "ws_started" not in st.session_state:
        st.session_state.ws_started = False
    if "candles" not in st.session_state:
        st.session_state.candles = pd.DataFrame()

    # ---------------- Login check ----------------
    if "ps_api" not in st.session_state:
        st.warning("⚠️ Please login first using your API credentials.")
    else:
        api = st.session_state["ps_api"]

        if not api.is_logged_in:
            ok, msg = api.login(st.session_state.get("otp", ""))
            if not ok:
                st.error(f"❌ Login failed: {msg}")
                st.stop()
            else:
                st.success("✅ Logged in successfully")

        # ---------------- Watchlist selection ----------------
        wl_resp = api.get_watchlists()
        watchlists = []
        if wl_resp:
            if isinstance(wl_resp, dict) and wl_resp.get("stat") == "Ok":
                watchlists = wl_resp.get("values", [])
            elif isinstance(wl_resp, list):
                watchlists = wl_resp
        watchlists = sorted(watchlists, key=int) if watchlists else []

        selected_watchlist = st.selectbox("Select Watchlist", watchlists)
        selected_interval = st.selectbox(
            "Select Interval",
            ["1", "3", "5", "10", "15", "30", "60", "120", "240"],
            index=2
        )

        # ---------------- Start WebSocket + Queue Thread ----------------
        if st.button("▶ Start Live Feed") and selected_watchlist:
            if not st.session_state.ws_started:

                def on_tick(tick_data):
                    tick = {
                        "symbol": tick_data.get("tk") or tick_data.get("symbol"),
                        "time": int(tick_data.get("ft")) // 1000 if "ft" in tick_data else int(time.time()),
                        "ltp": float(tick_data.get("lp") or tick_data.get("ltp") or 0),
                        "volume": int(tick_data.get("v", 1))
                    }
                    # Tick buffer update
                    api._tick_buffer.append(tick)

                    # Store in session_state for table
                    st.session_state.ticks[tick["symbol"]] = {
                        "LTP": tick["ltp"],
                        "Volume": tick["volume"],
                        "Time": datetime.now().strftime("%H:%M:%S")
                    }

                # ✅ Start websocket once
                api.start_websocket_for_symbols(selected_watchlist, callback=on_tick)
                st.session_state.ws_started = True
                st.success(f"✅ WebSocket started for watchlist: {selected_watchlist}")

                # ---------------- Thread-safe queue setup ----------------
                import threading, queue

                if "live_data_queue" not in st.session_state:
                    st.session_state["live_data_queue"] = queue.Queue()
                if "latest_live" not in st.session_state:
                    st.session_state["latest_live"] = pd.DataFrame()
                if "last_live_error" not in st.session_state:
                    st.session_state["last_live_error"] = None
                if "live_thread_started" not in st.session_state:
                    st.session_state["live_thread_started"] = False

                def live_fetch_loop(api, data_queue, error_store):
                    while True:
                        try:
                            df_live = api.build_live_candles(interval="1min")
                            if not df_live.empty:
                                data_queue.put(df_live)
                        except Exception as e:
                            error_store["last_live_error"] = str(e)
                        time.sleep(1)

                if not st.session_state["live_thread_started"] and "ps_api" in st.session_state:
                    t = threading.Thread(
                        target=live_fetch_loop,
                        args=(st.session_state["ps_api"], st.session_state["live_data_queue"], st.session_state),
                        daemon=True
                    )
                    t.start()
                    st.session_state["live_thread_started"] = True

        # ---------------- Streamlit Live Container ----------------
        st.subheader("📡 Live WebSocket Stream")
        live_container = st.empty()

        if "live_data_queue" in st.session_state and not st.session_state["live_data_queue"].empty():
            st.session_state["latest_live"] = st.session_state["live_data_queue"].get()
            print("📈 New live candle received")

        df_live_ui = st.session_state.get("latest_live", pd.DataFrame())
        if not df_live_ui.empty:
            fig = plot_tpseries_candles(df_live_ui, "WATCHLIST")
            if fig:
                live_container.plotly_chart(fig, use_container_width=True)
                live_container.dataframe(df_live_ui.tail(20), use_container_width=True, height=300)
        elif st.session_state.get("last_live_error"):
            live_container.warning(f"Live update error: {st.session_state['last_live_error']}")
        else:
            live_container.info("⏳ Waiting for live ticks...")


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

# === Tab 5: Strategy Engine (Full Live Compatible) ===
with tab5:
    st.subheader("📡 Live WebSocket Candles + TPSeries")

    if "ps_api" not in st.session_state:
        st.warning("⚠️ Please login first using your API credentials.")
    else:
        api = st.session_state["ps_api"]

        # 👇 yaha ensure karo ki login ho chuka hai
        if not api.is_logged_in:
            ok, msg = api.login(st.session_state.get("otp", ""))  # OTP agar UI se le rahe ho
            if not ok:
                st.error(f"❌ Login failed: {msg}")
                st.stop()
            else:
                st.success("✅ Logged in successfully")

        # --- Start WebSocket if not already ---
        if "ws_started" not in st.session_state:
            api.start_websocket_for_symbols(["TATAMOTORS-EQ"])
            st.session_state.ws_started = True

        # --- Initialize thread-safe queue for live data ---
        import queue
        if "live_data_queue" not in st.session_state:
            st.session_state["live_data_queue"] = queue.Queue()

        # --- Historical TPSeries Chart ---
        st.subheader("📊 TPSeries Historical Chart")
        wl_resp = api.get_watchlists()

        # Normalize watchlists
        watchlists = []
        if wl_resp is not None:
            if isinstance(wl_resp, dict) and wl_resp.get("stat") == "Ok":
                watchlists = wl_resp.get("values", [])
            elif isinstance(wl_resp, list):
                watchlists = wl_resp
        watchlists = sorted(watchlists, key=int) if watchlists else []

        selected_watchlist = st.selectbox("Select Watchlist", watchlists, key="wl_tab5")
        selected_interval = st.selectbox(
            "Select Interval",
            ["1", "3", "5", "10", "15", "30", "60", "120", "240"],
            index=2,
            key="int_tab5"
        )

        if st.button("🔁 Fetch TPSeries Data", key="fetch_tab5"):
            wl_data = api.get_watchlist(selected_watchlist)
            scrips = []
            if isinstance(wl_data, dict):
                scrips = wl_data.get("values", [])
            elif isinstance(wl_data, list):
                scrips = wl_data

            if not scrips:
                st.warning("No scrips found in this watchlist.")
            else:
                with st.spinner("Fetching TPSeries candle data..."):
                    for i, scrip in enumerate(scrips):
                        if not isinstance(scrip, dict):
                            continue
                        exch = scrip.get("exch") or scrip.get("exchange")
                        token = scrip.get("token")
                        tsym = scrip.get("tsym") or scrip.get("symbol")
                        if not (exch and token and tsym):
                            continue

                        try:
                            session_key = f"tpseries_{tsym}"
                            if session_key not in st.session_state:
                                df_candle = api.fetch_full_tpseries(exch, token, interval=selected_interval, chunk_days=5)
                                st.session_state[session_key] = df_candle.copy()
                            else:
                                df_candle = st.session_state[session_key]

                            if not df_candle.empty:
                                # Standardize datetime
                                datetime_col = next((c for c in ["datetime", "time", "date"] if c in df_candle.columns), None)
                                if datetime_col:
                                    df_candle.rename(columns={datetime_col: "datetime"}, inplace=True)
                                    df_candle["datetime"] = pd.to_datetime(df_candle["datetime"], errors="coerce", dayfirst=True)
                                    df_candle.dropna(subset=["datetime"], inplace=True)
                                    df_candle.sort_values("datetime", inplace=True)
                                else:
                                    st.warning(f"⚠️ Missing datetime column for {tsym}")
                                    continue

                                fig = plot_tpseries_candles(df_candle, tsym)
                                if fig:
                                    st.plotly_chart(fig, use_container_width=True)
                                    st.dataframe(df_candle, use_container_width=True, height=600)
                            else:
                                st.warning(f"No data for {tsym}")
                        except Exception as e:
                            st.warning(f"{tsym}: Exception occurred - {e}")

        # --- Live WebSocket Stream ---
        st.subheader("📡 Live WebSocket Stream")
        live_container = st.empty()

        # --- Start live fetch thread if not started ---
        if "live_update_thread_started" not in st.session_state:
            import threading, time

            def live_fetch_loop(api):
                while True:
                    try:
                        df_live = api.build_live_candles(interval="1min")
                        if df_live.empty and hasattr(api, "live_ticks"):
                            df_live = pd.DataFrame(api.live_ticks)
                            if not df_live.empty:
                                df_live = df_live.rename(columns={"time": "datetime", "price": "close"})
                                df_live["open"] = df_live["close"]
                                df_live["high"] = df_live["close"]
                                df_live["low"] = df_live["close"]

                        df_live = ensure_datetime(df_live)
                        if not df_live.empty:
                            st.session_state["live_data_queue"].put(df_live)  # Push safely to queue
                    except Exception as e:
                        st.session_state["live_error"] = str(e)
                    time.sleep(1)

            t = threading.Thread(target=live_fetch_loop, args=(api,), daemon=True)
            t.start()
            st.session_state["live_update_thread_started"] = True

        # --- Pull latest live data from queue ---
        if not st.session_state["live_data_queue"].empty():
            st.session_state["latest_live"] = st.session_state["live_data_queue"].get()

        # --- Render live data in main thread ---
        df_live_ui = st.session_state.get("latest_live", pd.DataFrame())
        if not df_live_ui.empty:
            fig = plot_tpseries_candles(df_live_ui, "TATAMOTORS-EQ")
            if fig:
                live_container.plotly_chart(fig, use_container_width=True)
                live_container.dataframe(df_live_ui.tail(20), use_container_width=True, height=300)
        elif "live_error" in st.session_state:
            live_container.warning(f"Live update error: {st.session_state['live_error']}")
        else:
            live_container.info("⏳ Waiting for live ticks...")




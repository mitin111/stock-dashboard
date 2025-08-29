
# main_app.py
import streamlit as st
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

# === Function: TPSeries fetch in daily chunks (fix for single candle issue) ===
def fetch_full_tpseries(api, exch, token, interval, days=60):
    final_df = pd.DataFrame()

    # IST timezone
    ist_offset = timedelta(hours=5, minutes=30)
    today_ist = datetime.utcnow() + ist_offset
    end_dt = today_ist
    start_dt = end_dt - timedelta(days=days)

    current_day = start_dt
    while current_day <= end_dt:
        day_start = current_day.replace(hour=9, minute=15, second=0, microsecond=0)
        day_end = current_day.replace(hour=15, minute=30, second=0, microsecond=0)

        # Convert to epoch seconds (UTC)
        st_epoch = int((day_start - ist_offset).timestamp())
        et_epoch = int((day_end - ist_offset).timestamp())

        resp = api.get_tpseries(exch, token, interval, st_epoch, et_epoch)

        if isinstance(resp, dict) and resp.get("stat") == "Ok" and "values" in resp:
            chunk_df = pd.DataFrame(resp["values"])
            chunk_df["datetime"] = pd.to_datetime(chunk_df["time"], unit="s", utc=True) + ist_offset
            chunk_df.set_index("datetime", inplace=True)
            final_df = pd.concat([final_df, chunk_df])
        else:
            # Weekend/holiday skip message
            pass  

        current_day += timedelta(days=1)
        time.sleep(0.3)  # Avoid rate limit

    final_df.sort_index(inplace=True)
    return final_df
# === Tab 5: Strategy Engine ===
with tab5:
    st.subheader("📉 TPSeries + Live Tick Data")

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import threading, queue
    import pandas as pd
    from datetime import datetime

    # --- Helper: Plot Candles ---
    def plot_tpseries_candles(df, symbol):
        if df.empty:
            fig = go.Figure()
            fig.update_layout(title=f"{symbol} - No data", template="plotly_dark", height=450)
            return fig

        df = df.drop_duplicates(subset=['datetime']).sort_values("datetime")
        df = df[(df['datetime'].dt.time >= pd.to_datetime("09:15").time()) &
                (df['datetime'].dt.time <= pd.to_datetime("15:30").time())]

        fig = make_subplots(rows=1, cols=1, shared_xaxes=True)
        fig.add_trace(go.Candlestick(
            x=df['datetime'],
            open=df['open'], high=df['high'],
            low=df['low'], close=df['close'],
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350',
            name='Price'
        ))

        fig.update_layout(
            xaxis_rangeslider_visible=False,
            dragmode='pan',
            hovermode='x unified',
            showlegend=False,
            template="plotly_dark",
            height=700,
            margin=dict(l=50, r=50, t=50, b=50),
            plot_bgcolor='black',
            paper_bgcolor='black',
            font=dict(color='white'),
            title=f"{symbol} - TradingView-style Chart"
        )
        fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='gray')
        fig.update_yaxes(showgrid=True, gridwidth=0.5, gridcolor='gray', fixedrange=False)
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]),
                                      dict(bounds=[15.5, 9.25], pattern="hour")])
        return fig

    # --- Live candle builder (robust + bucket aligned) ---
    def build_live_candle_from_tick(tick, selected_interval):
        try:
            ps = st.session_state.get("ps_api")
            if not ps:
                return

            ts_raw = tick.get("ft")
            if ts_raw is None:
                return
            ts = int(float(ts_raw))

            exch = tick.get("e", "").strip()
            tk = str(tick.get("tk", "")).strip()
            if not exch or not tk:
                return

            # Extract price + volume safely
            price = tick.get("lp")
            price = float(price) if price not in (None, "", "0") else None

            vol = tick.get("v")
            vol = float(vol) if vol not in (None, "", "0") else 0.0

            if not hasattr(ps, "candles") or ps.candles is None:
                ps.candles = {}

            m = int(selected_interval)
            bucket = ts - (ts % (m * 60))
            key = f"{exch}|{tk}|{m}"

            if key not in ps.candles:
                ps.candles[key] = {}

            # --- नया candle बनाना ---
            if bucket not in ps.candles[key]:
                if price is None:
                    return  # ❌ price बिना candle मत बनाओ
                ps.candles[key][bucket] = {
                    "ts": bucket,
                    "o": price, "h": price, "l": price, "c": price,
                    "v": vol,
                }
                return

            # --- Existing candle update ---
            c = ps.candles[key][bucket]

            if price is not None:
                c["c"] = price
                c["h"] = max(c.get("h", price), price)
                c["l"] = min(c.get("l", price), price)
                if "o" not in c:
                    c["o"] = price

            if vol:
                c["v"] = c.get("v", 0.0) + vol

        except Exception as e:
            print(f"⚠️ build_live_candle_from_tick error: {e}, tick={tick}")

    # --- WebSocket Start Helper ---
    def start_ws(symbols):
        if "tick_queue" not in st.session_state:
            st.session_state.tick_queue = queue.Queue()

        def on_tick_callback(tick):
            try:
                st.session_state.tick_queue.put(tick)
            except Exception as e:
                print("⚠️ tick_queue error:", e)

        ps_api._on_tick = on_tick_callback
        ps_api.connect_websocket(symbols)

    # --- UI ---
    if "ps_api" not in st.session_state:
        st.warning("⚠️ Please login first using your API credentials.")
    else:
        ps_api = st.session_state["ps_api"]
        wl_resp = ps_api.get_watchlists()

        if wl_resp.get("stat") == "Ok":
            raw_watchlists = wl_resp["values"]
            watchlists = sorted(raw_watchlists, key=int)
            selected_watchlist = st.selectbox("Select Watchlist", watchlists)
            selected_interval = st.selectbox(
                "Select Interval",
                ["1", "3", "5", "10", "15", "30", "60", "120", "240"],
                index=0
            )

            placeholder_ticks = st.empty()
            placeholder_chart = st.empty()

            if st.button("🚀 Start TPSeries + Live Feed"):
                with st.spinner("Fetching TPSeries + starting WebSocket..."):
                    wl_data = ps_api.get_watchlist(selected_watchlist)
                    if wl_data.get("stat") == "Ok":
                        scrips = wl_data.get("values", [])
                        symbols_for_ws = []

                        for i, scrip in enumerate(scrips):
                            exch, token, tsym = scrip["exch"], scrip["token"], scrip["tsym"]
                            st.write(f"📦 {i+1}. {tsym} → {exch}|{token}")

                            try:
                                df_candle = ps_api.fetch_full_tpseries(
                                    exch, token,
                                    interval=selected_interval,
                                    chunk_days=5
                                )
                                if not df_candle.empty:
                                    if "datetime" not in df_candle.columns:
                                        for col in ["time", "date"]:
                                            if col in df_candle.columns:
                                                df_candle.rename(columns={col: "datetime"}, inplace=True)

                                    df_candle["datetime"] = pd.to_datetime(df_candle["datetime"], errors="coerce")
                                    df_candle.dropna(subset=["datetime"], inplace=True)
                                    df_candle.sort_values("datetime", inplace=True)

                                    # Seed ps_api.candles
                                    key = f"{exch}|{token}|{int(selected_interval)}"
                                    if not hasattr(ps_api, "candles") or ps_api.candles is None:
                                        ps_api.candles = {}
                                    if key not in ps_api.candles:
                                        ps_api.candles[key] = {}
                                    for idx, row in df_candle.iterrows():
                                        ts_epoch = int(row["datetime"].timestamp())
                                        ps_api.candles[key][ts_epoch] = {
                                            "ts": ts_epoch,
                                            "o": row["open"], "h": row["high"],
                                            "l": row["low"], "c": row["close"],
                                            "v": row.get("volume", 0),
                                        }

                                    # Initial chart
                                    fig = plot_tpseries_candles(df_candle, tsym)
                                    placeholder_chart.plotly_chart(fig, use_container_width=True)

                                    symbols_for_ws.append(f"{exch}|{token}")

                            except Exception as e:
                                st.warning(f"⚠️ {tsym}: Exception - {e}")

                        st.success(f"✅ TPSeries fetched for {len(symbols_for_ws)} scrips")

                        if symbols_for_ws and "ws_started" not in st.session_state:
                            threading.Thread(target=start_ws, args=(symbols_for_ws,), daemon=True).start()
                            st.session_state.ws_started = True
                            st.session_state.symbols_for_ws = symbols_for_ws
                            st.info(f"🔗 WebSocket started for {len(symbols_for_ws)} symbols")

            # --- Live Tick Consumer + Chart Refresh ---
            if "tick_queue" in st.session_state:
                ticks = []
                while not st.session_state.tick_queue.empty():
                    tick = st.session_state.tick_queue.get()
                    ticks.append(tick)
                    build_live_candle_from_tick(tick, selected_interval)

                if ticks:
                    if "df_ticks" not in st.session_state:
                        st.session_state.df_ticks = pd.DataFrame(ticks)
                    else:
                        st.session_state.df_ticks = pd.concat(
                            [st.session_state.df_ticks, pd.DataFrame(ticks)]
                        ).tail(2000)

                    placeholder_ticks.dataframe(st.session_state.df_ticks.tail(10), use_container_width=True)

                    for sym in st.session_state.get("symbols_for_ws", []):
                        try:
                            exch, token = sym.split("|")
                        except:
                            continue
                        key = f"{exch}|{token}|{int(selected_interval)}"
                        if hasattr(ps_api, "candles") and key in ps_api.candles:
                            df_candles = pd.DataFrame(list(ps_api.candles[key].values()))
                            if df_candles.empty:
                                continue
                            df_candles["datetime"] = pd.to_datetime(df_candles["ts"], unit="s")
                            df_candles.sort_values("datetime", inplace=True)
                            df_candles.rename(columns={
                                "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"
                            }, inplace=True)

                            fig = plot_tpseries_candles(df_candles, f"{exch}|{token}")
                            placeholder_chart.plotly_chart(fig, use_container_width=True)
                else:
                    placeholder_ticks.info("⏳ Waiting for live ticks...")

        else:
            st.warning(wl_resp.get("emsg", "Could not fetch watchlists."))

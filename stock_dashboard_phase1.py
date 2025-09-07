
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

            st.session_state.all_watchlists = watchlists
            st.session_state.selected_watchlist = selected_wl

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
    st.subheader("📉 TPSeries + Live Tick Data (blink-free)")

    import plotly.graph_objects as go
    import threading, queue, time
    import pandas as pd
    pd.set_option('future.no_silent_downcasting', True)
    from datetime import datetime

    # --- Define Indian market holidays (global) ---
    full_holidays = pd.to_datetime([
        "2025-02-26","2025-03-14","2025-03-31","2025-04-10","2025-04-14",
        "2025-04-18","2025-05-01","2025-08-15","2025-08-27",
        "2025-10-02","2025-10-21","2025-10-22","2025-11-05","2025-12-25"
    ]).normalize()

    holiday_breaks = []
    for h in full_holidays:
        times = pd.date_range(h + pd.Timedelta(hours=9, minutes=15),
                              h + pd.Timedelta(hours=15, minutes=30),
                              freq="5min")   # agar tumhara interval 5 min hai
        holiday_breaks.extend(times.to_pydatetime().tolist())

    # ✅ Guard clause
    if "ps_api" not in st.session_state or "selected_watchlist" not in st.session_state:
        st.warning("⚠️ Please login and select a watchlist in Tab 1 before starting live feed.")
        st.stop()

    ps_api = st.session_state.ps_api
    watchlists = st.session_state.get("all_watchlists", [])
    wl_labels = [f"Watchlist {wl}" for wl in watchlists]
    current_wl = st.session_state.get("selected_watchlist", watchlists[0])
    selected_label = st.selectbox(
        "📁 Select Watchlist for Live Feed",
        wl_labels,
        index=wl_labels.index(f"Watchlist {current_wl}") if current_wl in watchlists else 0
    )
    selected_watchlist = dict(zip(wl_labels, watchlists))[selected_label]
    st.session_state.selected_watchlist = selected_watchlist

    interval_options = ["1","3","5","10","15","30","60","120","240"]
    default_interval = st.session_state.get("saved_interval", "1")
    selected_interval = st.selectbox(
        "⏱️ Candle Interval (minutes)",
        interval_options,
        index=interval_options.index(default_interval)
    )
    if st.button("💾 Save Interval"):
        st.session_state.saved_interval = selected_interval
        st.success(f"Interval saved: {selected_interval} min")

    # --- Shared UI Queue ---
    if "ui_queue" not in st.session_state:
        st.session_state.ui_queue = queue.Queue()
    ui_queue = st.session_state.ui_queue

    # --- Ensure basic session_state keys ---
    for key, default in {
        "ohlc_x": [], "ohlc_o": [], "ohlc_h": [],
        "ohlc_l": [], "ohlc_c": [],
        "live_feed_flag": {"active": False},
        "ws_started": False, "symbols_for_ws": []
    }.items():
        if key not in st.session_state:
            st.session_state[key] = default

    # --- Placeholders ---
    placeholder_status = st.empty()
    placeholder_ticks = st.empty()
    placeholder_chart = st.empty()

    # --- Try to use FigureWidget (blink-free updates) ---
    USE_FIGWIDGET = True
    try:
        _ = go.FigureWidget
    except Exception:
        USE_FIGWIDGET = False

    if "live_fig_type" not in st.session_state:
        st.session_state.live_fig_type = "figwidget" if USE_FIGWIDGET else "figure"

    # --- Create figure once (persistent) ---
    if "live_fig" not in st.session_state:
        if st.session_state.live_fig_type == "figwidget":
            st.session_state.live_fig = go.FigureWidget()
            st.session_state.live_fig.add_candlestick(
                x=st.session_state.ohlc_x,
                open=st.session_state.ohlc_o,
                high=st.session_state.ohlc_h,
                low=st.session_state.ohlc_l,
                close=st.session_state.ohlc_c,
                increasing_line_color='#26a69a',
                decreasing_line_color='#ef5350',
                name="Price"
            )
        else:
            st.session_state.live_fig = go.Figure()
            st.session_state.live_fig.add_trace(go.Candlestick(
                x=st.session_state.ohlc_x,
                open=st.session_state.ohlc_o,
                high=st.session_state.ohlc_h,
                low=st.session_state.ohlc_l,
                close=st.session_state.ohlc_c,
                increasing_line_color='#26a69a',
                decreasing_line_color='#ef5350',
                name="Price"
            ))

        st.session_state.live_fig.update_layout(
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            height=700,
            transition_duration=0
        )
        st.session_state.live_fig.update_xaxes(
            type="date",
            tickformat="%d-%m %H:%M",
            tickangle=0,
            rangeslider_visible=False,
            rangebreaks=[
                dict(bounds=["sat", "mon"]),           # weekends
                dict(bounds=[15.5, 9.25], pattern="hour"),    # market close
                dict(values=holiday_breaks)
            ]
        )

    # --- Render chart once ---
    placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)

    # --- Candle updater from tick ---
    def update_last_candle_from_tick_local(tick, interval=1):
        try:
            ts = int(tick.get("ft") or tick.get("time"))  # epoch seconds
            dt = datetime.fromtimestamp(ts, tz=pd.Timestamp.now().tz)

            minute = (dt.minute // interval) * interval
            candle_time = dt.replace(second=0, microsecond=0, minute=minute)
            if st.session_state.get("last_tp_dt") and candle_time <= st.session_state.last_tp_dt:
                 return

            price = float(tick["lp"])
            vol = float(tick.get("v", 0))

            if st.session_state.ohlc_x and st.session_state.ohlc_x[-1] == candle_time:
                st.session_state.ohlc_h[-1] = max(st.session_state.ohlc_h[-1], price)
                st.session_state.ohlc_l[-1] = min(st.session_state.ohlc_l[-1], price)
                st.session_state.ohlc_c[-1] = price
            else:
                st.session_state.ohlc_x.append(candle_time)
                st.session_state.ohlc_o.append(price)
                st.session_state.ohlc_h.append(price)
                st.session_state.ohlc_l.append(price)
                st.session_state.ohlc_c.append(price)

            trace = st.session_state.live_fig.data[0]
            trace.x = st.session_state.ohlc_x
            trace.open = st.session_state.ohlc_o
            trace.high = st.session_state.ohlc_h
            trace.low = st.session_state.ohlc_l
            trace.close = st.session_state.ohlc_c

        except Exception as e:
            placeholder_ticks.warning(f"⚠️ Candle update error: {e}")

    # --- Helpers ---
    def normalize_datetime(df_candle: pd.DataFrame):
        cols = [c for c in df_candle.columns if "date" in c.lower() or "time" in c.lower()]
        if not cols:
            raise KeyError("No date/time column found in TPSeries data")
        df_candle["datetime"] = pd.to_datetime(df_candle[cols[0]], errors="coerce")
        df_candle.dropna(subset=["datetime"], inplace=True)
        df_candle.sort_values("datetime", inplace=True)
        return df_candle

    def _update_local_ohlc_from_df(df_candle):
        if isinstance(df_candle.index, pd.DatetimeIndex):
            x_vals = list(df_candle.index)
        elif "datetime" in df_candle.columns:
            x_vals = list(pd.to_datetime(df_candle["datetime"], errors="coerce"))
        else: 
            raise KeyError("❌ datetime column missing in DataFrame")
            
        st.session_state.ohlc_x = x_vals
        st.session_state.ohlc_o = list(df_candle["open"].astype(float))
        st.session_state.ohlc_h = list(df_candle["high"].astype(float))
        st.session_state.ohlc_l = list(df_candle["low"].astype(float))
        st.session_state.ohlc_c = list(df_candle["close"].astype(float))
        try:
            trace = st.session_state.live_fig.data[0]
            trace.x = st.session_state.ohlc_x
            trace.open = st.session_state.ohlc_o
            trace.high = st.session_state.ohlc_h
            trace.low = st.session_state.ohlc_l
            trace.close = st.session_state.ohlc_c
        except Exception:
            st.session_state.live_fig.data = []
            st.session_state.live_fig.add_trace(go.Candlestick(
                x=st.session_state.ohlc_x,
                open=st.session_state.ohlc_o,
                high=st.session_state.ohlc_h,
                low=st.session_state.ohlc_l,
                close=st.session_state.ohlc_c,
                increasing_line_color='#26a69a',
                decreasing_line_color='#ef5350',
                name="Price"
            ))
             # ✅ PATCH: Save last historical datetime for overlap guard
             if len(st.session_state.ohlc_x) > 0:
                 st.session_state.last_tp_dt = st.session_state.ohlc_x[-1]
             else:
                 st.session_state.last_tp_dt = None

    # --- WebSocket forwarder (THREAD) ---
    def start_ws(symbols, ps_api, ui_queue):
        def on_tick_callback(tick):
            try:
                ui_queue.put(tick, block=False)
            except Exception:
                pass
        try:
            ps_api.connect_websocket(symbols, on_tick=on_tick_callback, tick_file="ticks_tab5.log")
        except Exception as e:
            st.error(f"WS start error: {e}")

    # --- Load TPSeries once + chart render ---
    scrips = ps_api.get_watchlist(selected_watchlist).get("values", [])
    symbols_for_ws = [f"{s['exch']}|{s['token']}" for s in scrips]

    if st.button("🚀 Start TPSeries + Live Feed"):
        if scrips:
            s = scrips[0]
            try:
                df = ps_api.fetch_full_tpseries(s["exch"], s["token"], interval=selected_interval, chunk_days=60)
            except Exception as e:
                st.warning(f"TPSeries fetch failed: {e}")
                df = None

            if df is not None and not df.empty:
                try:
                    df = normalize_datetime(df)
                except Exception:
                    timecols = [c for c in df.columns if "date" in c.lower() or "time" in c.lower()]
                    if timecols:
                        df["datetime"] = pd.to_datetime(df[timecols[0]], errors="coerce")
                        df.dropna(subset=["datetime"], inplace=True)
                        df.sort_values("datetime", inplace=True)

                # ✅ Clean holidays & duplicates (final fix)
                if "datetime" in df.columns:
                    df = df[~df["datetime"].dt.normalize().isin(full_holidays)]
                    df = df.drop_duplicates(subset="datetime", keep="last")
                    df = df.reset_index(drop=True)
                    df["datetime"] = pd.to_datetime(df["datetime"])
                    df.set_index("datetime", inplace=True)
     
                # Convert OHLC properly
                for col in ["open","high","low","close"]:
                    df[col] = pd.to_numeric(df[col].ffill(), errors="coerce")
                df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)

                # Update chart
                _update_local_ohlc_from_df(df)
                placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)

        if symbols_for_ws:
            if not st.session_state.ws_started:
                threading.Thread(target=start_ws, args=(symbols_for_ws, ps_api, ui_queue), daemon=True).start()
                st.session_state.ws_started = True
                st.session_state.symbols_for_ws = symbols_for_ws
                st.info(f"📡 WebSocket started for {len(symbols_for_ws)} symbols.")
        else:
            st.info("No symbols to start WS for.")

    if st.button("🛑 Stop Live Feed"):
        st.session_state.live_feed_flag["active"] = False
        st.session_state.ws_started = False
        st.info("🛑 Live feed stopped.")

    # --- Drain ui_queue ---
    processed = 0
    last_tick = None
    for _ in range(200):
        try:
            tick = ui_queue.get_nowait()
        except queue.Empty:
            break
        else:
            update_last_candle_from_tick_local(tick, interval=int(selected_interval))
            processed += 1
            last_tick = tick

    if processed > 0:
        if st.session_state.live_fig_type != "figwidget":
            placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)
        if last_tick:
            placeholder_ticks.json(last_tick)

    placeholder_status.info(
        f"WS started: {st.session_state.get('ws_started', False)} | "
        f"symbols: {len(st.session_state.get('symbols_for_ws', []))} | "
        f"queue: {ui_queue.qsize()} | processed: {processed} | "
        f"display_len: {len(st.session_state.ohlc_x)}"
    )

    if processed == 0 and ui_queue.qsize() == 0 and (not st.session_state.ohlc_x):
        placeholder_ticks.info("⏳ Waiting for first ticks...")















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
import pytz

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

# === Tab 5: Strategy Engine ===
with tab5:
    st.subheader("📉 TPSeries + Live Tick Data (auto-start, blink-free)")

    import plotly.graph_objects as go
    import threading, queue, time
    import pandas as pd, pytz
    pd.set_option('future.no_silent_downcasting', True)
    from datetime import datetime, timedelta

    # --- Initialize session state defaults ---
    for key, default in {
        "live_feed_flag": {"active": False},
        "ws_started": False,
        "ohlc_x": [], "ohlc_o": [], "ohlc_h": [], "ohlc_l": [], "ohlc_c": [],
        "live_fig": None,
        "last_tp_dt": None,
        "symbols_for_ws": []
    }.items():
        if key not in st.session_state:
            st.session_state[key] = default

    # --- Define Indian market holidays (global) ---
    full_holidays = pd.to_datetime([
        "2025-02-26","2025-03-14","2025-03-31","2025-04-10","2025-04-14",
        "2025-04-18","2025-05-01","2025-08-15","2025-08-27",
        "2025-10-02","2025-10-21","2025-10-22","2025-11-05","2025-12-25"
    ]).normalize()

    # Precompute holiday rangebreak datetimes (plotly expects datetimes)
    holiday_breaks = []
    for h in full_holidays:
        times = pd.date_range(h + pd.Timedelta(hours=9, minutes=15),
                              h + pd.Timedelta(hours=15, minutes=30),
                              freq="5min")
        holiday_breaks.extend(times.to_pydatetime().tolist())

    # ✅ Guard clause
    if "ps_api" not in st.session_state or "selected_watchlist" not in st.session_state:
        st.warning("⚠️ Please login and select a watchlist in Tab 1 before starting live feed.")
        st.stop()

    ps_api = st.session_state.ps_api

    # UI controls
    watchlists = st.session_state.get("all_watchlists", [])
    wl_labels = [f"Watchlist {wl}" for wl in watchlists]
    current_wl = st.session_state.get("selected_watchlist", watchlists[0] if watchlists else None)
    selected_label = st.selectbox("📁 Select Watchlist for Live Feed",
                                  wl_labels,
                                  index=wl_labels.index(f"Watchlist {current_wl}") if current_wl in watchlists else 0)
    selected_watchlist = dict(zip(wl_labels, watchlists))[selected_label]
    st.session_state.selected_watchlist = selected_watchlist

    interval_options = ["1","3","5","10","15","30","60","120","240"]
    default_interval = st.session_state.get("saved_interval", "5")
    selected_interval = st.selectbox("⏱️ Candle Interval (minutes)",
                                     interval_options,
                                     index=interval_options.index(default_interval))
    if st.button("💾 Save Interval"):
        st.session_state.saved_interval = selected_interval
        st.success(f"Interval saved: {selected_interval} min")

    # --- Shared UI Queue ---
    if "ui_queue" not in st.session_state:
        st.session_state.ui_queue = queue.Queue()
    ui_queue = st.session_state.ui_queue

    # --- Placeholders ---
    placeholder_status = st.empty()
    placeholder_ticks = st.empty()
    placeholder_chart = st.empty()

    # --- Load scrips & prepare WS symbol list ---
    scrips = ps_api.get_watchlist(selected_watchlist).get("values", [])
    symbols_for_ws = [f"{s['exch']}|{s['token']}" for s in scrips]

    # --- Figure init (only once) ---
    if st.session_state.live_fig is None:
        st.session_state.live_fig = go.Figure()
        st.session_state.live_fig.add_trace(go.Candlestick(
            x=[], open=[], high=[], low=[], close=[],
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
            name="Price"
        ))
        st.session_state.live_fig.update_layout(
            xaxis=dict(
                rangeslider_visible=False,
                type="date"
            ),
            yaxis=dict(
                fixedrange=False  # y-axis zoom allowed
            ),    
            dragmode="pan",
            hovermode="x unified",
            showlegend=False,
            template="plotly_dark",
            height=700,
            margin=dict(l=50, r=50, t=50, b=50),
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white"),
            transition_duration=0,
        )

    # --- Helper: write ohlc arrays into session_state and figure (without clearing history unless intended) ---
    def load_history_into_state(df_history):
        # df_history: indexed by tz-aware Asia/Kolkata datetime, cols open/high/low/close, numeric
        df_history = df_history.sort_index()
        st.session_state.ohlc_x = list(df_history.index)
        st.session_state.ohlc_o = list(df_history["open"].astype(float))
        st.session_state.ohlc_h = list(df_history["high"].astype(float))
        st.session_state.ohlc_l = list(df_history["low"].astype(float))
        st.session_state.ohlc_c = list(df_history["close"].astype(float))

        # Replace existing trace 0 with full history (blink-free)
        st.session_state.live_fig.data = []
        st.session_state.live_fig.add_trace(go.Candlestick(
            x=st.session_state.ohlc_x,
            open=st.session_state.ohlc_o,
            high=st.session_state.ohlc_h,
            low=st.session_state.ohlc_l,
            close=st.session_state.ohlc_c,
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
            name="History"
        ))
        st.session_state.last_tp_dt = st.session_state.ohlc_x[-1] if st.session_state.ohlc_x else None

    # --- Update last candle from tick (blink-free) ---
    def update_last_candle_from_tick_local(tick, interval=1):
        try:
            ts = int(tick.get("ft") or tick.get("time") or 0)
            if ts == 0:
                return
            # tick timestamp is epoch seconds UTC -> convert to IST
            dt = datetime.fromtimestamp(ts, tz=pytz.UTC).astimezone(pytz.timezone("Asia/Kolkata"))

            minute = (dt.minute // interval) * interval
            candle_time = dt.replace(second=0, microsecond=0, minute=minute)

            price = None
            if "lp" in tick and tick["lp"] not in (None, "", "NA"):
                try:
                    price = float(tick["lp"])
                except Exception:
                    price = None
            if price is None:
                return

            # if no history loaded yet, initialize with this candle
            if not st.session_state.ohlc_x:
                st.session_state.ohlc_x = [candle_time]
                st.session_state.ohlc_o = [price]
                st.session_state.ohlc_h = [price]
                st.session_state.ohlc_l = [price]
                st.session_state.ohlc_c = [price]
                st.session_state.last_tp_dt = candle_time
            else:
                # Only update if candle_time is >= last known (allow new session)
                if st.session_state.last_tp_dt is None or candle_time > st.session_state.last_tp_dt:
                    # New candle after last TPSeries candle: append
                    st.session_state.ohlc_x.append(candle_time)
                    st.session_state.ohlc_o.append(price)
                    st.session_state.ohlc_h.append(price)
                    st.session_state.ohlc_l.append(price)
                    st.session_state.ohlc_c.append(price)
                    st.session_state.last_tp_dt = candle_time
                elif candle_time == st.session_state.ohlc_x[-1]:
                    # update existing last candle values
                    st.session_state.ohlc_h[-1] = max(st.session_state.ohlc_h[-1], price)
                    st.session_state.ohlc_l[-1] = min(st.session_state.ohlc_l[-1], price)
                    st.session_state.ohlc_c[-1] = price
                else:
                    # tick older than last candle -> ignore
                    return

            # update the single trace in place (blink-free)
            if st.session_state.live_fig.data:
                trace = st.session_state.live_fig.data[0]
                trace.x = st.session_state.ohlc_x
                trace.open = st.session_state.ohlc_o
                trace.high = st.session_state.ohlc_h
                trace.low = st.session_state.ohlc_l
                trace.close = st.session_state.ohlc_c
            else:
                st.session_state.live_fig.add_trace(go.Candlestick(
                    x=st.session_state.ohlc_x,
                    open=st.session_state.ohlc_o,
                    high=st.session_state.ohlc_h,
                    low=st.session_state.ohlc_l,
                    close=st.session_state.ohlc_c,
                    increasing_line_color="#26a69a",
                    decreasing_line_color="#ef5350",
                    name="Live"
                ))

            # refresh the chart
            placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)

        except Exception as e:
            placeholder_ticks.warning(f"⚠️ Candle update error: {e}")

    # --- WS forwarder (uses ps_api.connect_websocket) ---
    def start_ws(symbols, ps_api, ui_queue):
        def on_tick_callback(tick):
            try:
                ui_queue.put(("tick", tick), block=False)
            except Exception:
                pass
        try:
            ws = ps_api.connect_websocket(symbols, on_tick=on_tick_callback, tick_file="ticks_tab5.log")
            # heartbeat thread
            def heartbeat(ws):
                while True:
                    if not st.session_state.get("live_feed_flag", {}).get("active", False):
                        break
                    try:
                        ws.send("ping")
                        hb = datetime.now().strftime("%H:%M:%S")
                        ui_queue.put(("heartbeat", hb), block=False)
                    except Exception:
                        break
                    time.sleep(20)
            threading.Thread(target=heartbeat, args=(ws,), daemon=True).start()
        except Exception as e:
            ui_queue.put(("ws_error", str(e)), block=False)

    # --- Preload TPSeries history and auto-start WS ---
    # Fetch history for the watchlist (first symbol)
    wl = st.session_state.selected_watchlist
    interval = selected_interval
    try:
        tpseries_results = ps_api.fetch_tpseries_for_watchlist(wl, interval)
    except Exception as e:
        tpseries_results = []
        st.warning(f"TPSeries fetch error: {e}")

    if tpseries_results:
        df = tpseries_results[0]["data"].copy()
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
            df["datetime"] = df["datetime"].dt.tz_localize("Asia/Kolkata", nonexistent="shift_forward", ambiguous="NaT")
            df = df.dropna(subset=["datetime"]).set_index("datetime")
            for col in ["into", "inth", "intl", "intc", "intv", "open", "high", "low", "close", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                if "into" in df.columns and "open" not in df.columns:
                    df = df.rename(columns={"into": "open", "inth": "high", "intl": "low", "intc": "close", "intv": "volume"})
                df = df.dropna(subset=["open", "high", "low", "close"])
                load_history_into_state(df)
                st.write(f"📊 Loaded TPSeries candles: {len(df)}")

                if full_holidays is not None and len(full_holidays) > 0:
                    holiday_breaks = []
                    for h in full_holidays:
                        h = pd.Timestamp(h).tz_localize("Asia/Kolkata").to_pydatetime()
                        holiday_breaks.append(h)
                    holiday_values = [h.replace(tzinfo=None) for h in holiday_breaks]

                    if "tpseries_debug_done" not in st.session_state:
                        st.write("sample holiday:", holiday_values[0])
                        st.write("holiday tzinfo (raw):", holiday_breaks[0].tzinfo)
                        if "ohlc_x" in st.session_state and st.session_state.ohlc_x:
                            st.write("sample ohlc_x[0] type:", str(type(st.session_state.ohlc_x[0])),
                                     "value:", st.session_state.ohlc_x[0])
                            st.write("ohlc_x tzinfo:", st.session_state.ohlc_x[0].tzinfo)
                        else:
                            st.write("ohlc_x empty")

                        st.write("sample holiday_breaks[0]:", holiday_breaks[0])
                        st.write("holiday_breaks types:", [type(b) for b in holiday_breaks[:3]])
                        st.write("holiday_breaks tzinfo:", holiday_breaks[0].tzinfo)
                        st.write("holiday_breaks final (session IST):", holiday_breaks[:3])

                        st.session_state.tpseries_debug_done = True

                        if "holiday_values" not in st.session_state or "holiday_breaks" not in st.session_state:
                            holiday_values = [pd.Timestamp(h).to_pydatetime().replace(tzinfo=None) for h in full_holidays]
                            holiday_breaks = []
                            for h in full_holidays:
                                start = pd.Timestamp(h).tz_localize("Asia/Kolkata").replace(hour=9, minute=15)
                                end   = pd.Timestamp(h).tz_localize("Asia/Kolkata").replace(hour=15, minute=30)
                                start_naive = start.to_pydatetime().replace(tzinfo=None)
                                end_naive   = end.to_pydatetime().replace(tzinfo=None)
                                holiday_breaks.append(dict(bounds=[start_naive, end_naive]))
                            st.session_state.holiday_values = holiday_values
                            st.session_state.holiday_breaks = holiday_breaks
                            st.write("holiday_breaks final (session IST):", holiday_breaks[:3])
                        else:
                            holiday_values = st.session_state.holiday_values
                            holiday_breaks = st.session_state.holiday_breaks

                        st.session_state.live_fig.update_xaxes(
                            showgrid=True, gridwidth=0.5, gridcolor="gray",
                            type="date",
                            tickformat="%d-%m-%Y\n%H:%M",
                            tickangle=0,
                            rangeslider_visible=False,
                            rangebreaks=[
                                dict(bounds=["sat", "mon"]),    # weekends skip
                                dict(bounds=[15.5, 9.25], pattern="hour"),  # non-market hours skip
                                *holiday_breaks
                            ]
                        )
                        placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)
                        # --- Auto-start websocket (only once) ---
                        if symbols_for_ws and not st.session_state.ws_started:
                            st.session_state.live_feed_flag["active"] = True
                            threading.Thread(target=start_ws, args=(symbols_for_ws, ps_api, ui_queue), daemon=True).start()
                            st.session_state.ws_started = True
                            st.session_state.symbols_for_ws = symbols_for_ws
                            st.info(f"📡 WebSocket started for {len(symbols_for_ws)} symbols.")
                            
        else:
            st.error("⚠️ No datetime column in TPSeries data")
    else:
        st.warning("⚠️ No TPSeries data fetched")

    # --- Drain queue and apply live ticks to last candle ---
    # This block runs each script run and consumes queued ticks (non-blocking)
    if st.session_state.live_feed_flag.get("active", False):
        processed = 0; 
        last_tick = None
        for _ in range(500):  # consume up to N ticks each run
            try:
                msg_type, payload = ui_queue.get_nowait()
            except queue.Empty:
                break
            else:
                if msg_type == "tick":
                    update_last_candle_from_tick_local(payload, interval=int(selected_interval))
                    processed += 1
                    last_tick = payload
                elif msg_type == "heartbeat":
                    st.session_state.last_heartbeat = payload
                elif msg_type == "ws_error":
                    placeholder_status.error(f"WS start error: {payload}")

        placeholder_status.info(
            f"WS started: {st.session_state.get('ws_started', False)} | "
            f"symbols: {len(st.session_state.get('symbols_for_ws', []))} | "
            f"queue: {ui_queue.qsize()} | processed: {processed} | "
            f"display_len: {len(st.session_state.ohlc_x)}"
        )
        if "last_heartbeat" in st.session_state:
            placeholder_status.info(f"📡 Last heartbeat: {st.session_state.last_heartbeat}")
            
        if processed == 0 and ui_queue.qsize() == 0 and (not st.session_state.ohlc_x):
            placeholder_ticks.info("⏳ Waiting for first ticks...")

    # --- "Go to latest" control uses ohlc_x as source of truth ---
    if len(st.session_state.ohlc_x) > 50:
        start_range = st.session_state.ohlc_x[-50]
    elif len(st.session_state.ohlc_x) > 0:
        start_range = st.session_state.ohlc_x[0]
    else:
        start_range = None
    end_range = st.session_state.ohlc_x[-1] if len(st.session_state.ohlc_x) > 0 else None

    st.session_state.live_fig.update_layout(
        updatemenus=[dict(
            type="buttons",
            direction="left",
            x=1, y=1.15,
            buttons=[dict(
                label="Go to Latest",
                method="relayout",
                args=[{"xaxis.range": [start_range, end_range]}]
            )]
        )]
    )

    st.session_state.live_fig.update_yaxes(
        showgrid=True, gridwidth=0.5, gridcolor="gray", fixedrange=False
    )

    from tkp_trm_chart import plot_trm_chart
     # --- Render TKP TRM + PAC + YHL chart ---
    if "ohlc_x" in st.session_state and len(st.session_state.ohlc_x) > 20:
        df_live = pd.DataFrame({
            "open": st.session_state.ohlc_o,
            "high": st.session_state.ohlc_h,
            "low": st.session_state.ohlc_l,
            "close": st.session_state.ohlc_c
        }, index=pd.to_datetime(st.session_state.ohlc_x))
        if df_live.index.tz is None:
            df_live.index = df_live.index.tz_localize("Asia/Kolkata")
        else:
            df_live.index = df_live.index.tz_convert("Asia/Kolkata")
        interval_min = int(selected_interval)
        full_index = pd.date_range(
            start=df_live.index.min(),
            end=df_live.index.max(),
            freq=f"{interval_min}min",
            tz="Asia/Kolkata"
        )     
        df_live = df_live.reindex(full_index).ffill()
        trm_traces = plot_trm_chart(df_live) 
        
        st.session_state.live_fig.data = st.session_state.live_fig.data[:1]
        for t in trm_traces:
            st.session_state.live_fig.add_trace(t)

    placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)









# stock_dashboard_phase1.py
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

    if "ps_api" not in st.session_state or not st.session_state.ps_api.is_logged_in():
        st.warning("⚠️ Please login first to view Dashboard.")
    else:
        ps_api = st.session_state.ps_api

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 📑 Order Book")
            try:
                ob = ps_api.order_book()
                if isinstance(ob, list) and len(ob) > 0:
                    df_ob = pd.DataFrame(ob)
                    st.dataframe(df_ob[["exch","tsym","trantype","qty","prc","prctyp","status","norenordno"]])
                else:
                    st.info("No orders found.")
            except Exception as e:
                st.error(f"❌ Error fetching Order Book: {e}")

        with col2:
            st.markdown("### 📑 Trade Book")
            try:
                tb = ps_api.trade_book()
                if isinstance(tb, list) and len(tb) > 0:
                    df_tb = pd.DataFrame(tb)
                    st.dataframe(df_tb[["exch","tsym","trantype","fillshares","avgprc","norenordno"]])
                else:
                    st.info("No trades found.")
            except Exception as e:
                st.error(f"❌ Error fetching Trade Book: {e}")
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
    from tab4_auto_trader import render_tab4
    # require_session_settings=True will disallow using file defaults.
    render_tab4(require_session_settings=True, allow_file_fallback=False)
        
# === Tab 5: Strategy Engine (clean, safe, blink-free) ===
with tab5:
    st.subheader("📉 TPSeries + Live Tick Data (auto-start, blink-free)")

    # --- Session & ps_api guard (top) ---
    ps_api = st.session_state.get("ps_api")
    if not ps_api or not getattr(ps_api, "is_logged_in", lambda: False)():
        st.warning("⚠️ Please login and select a watchlist in Tab 1 before starting live feed.")
        st.stop()

    import plotly.graph_objects as go
    import threading, queue, time
    import pandas as pd, pytz
    pd.set_option('future.no_silent_downcasting', True)
    from datetime import datetime, timedelta
    from plotly.subplots import make_subplots
    from tkp_trm_chart import plot_trm_chart, get_trm_settings

    # --- Initialize session state defaults (only set if missing) ---
    defaults = {
        "live_feed_flag": {"active": False},
        "ws_started": False,
        "ohlc_x": [], "ohlc_o": [], "ohlc_h": [], "ohlc_l": [], "ohlc_c": [],
        "live_fig": None,
        "last_tp_dt": None,
        "symbols_for_ws": [],
        "_last_plot_key": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # UI controls
    watchlists = st.session_state.get("all_watchlists", [])
    wl_labels = [f"Watchlist {wl}" for wl in watchlists] or ["Watchlist None"]
    current_wl = st.session_state.get("selected_watchlist", watchlists[0] if watchlists else None)
    selected_label = st.selectbox("📁 Select Watchlist for Live Feed",
                                  wl_labels,
                                  index=wl_labels.index(f"Watchlist {current_wl}") if current_wl in watchlists else 0)
    selected_watchlist = dict(zip(wl_labels, watchlists)).get(selected_label, current_wl)
    st.session_state.selected_watchlist = selected_watchlist

    interval_options = ["1","3","5","10","15","30","60","120","240"]
    default_interval = st.session_state.get("saved_interval", "5")
    selected_interval = st.selectbox("⏱️ Candle Interval (minutes)",
                                     interval_options,
                                     index=interval_options.index(default_interval) if default_interval in interval_options else 2)
    if st.button("💾 Save Interval"):
        st.session_state.saved_interval = selected_interval
        st.success(f"Interval saved: {selected_interval} min")

    # Shared UI queue (persistent)
    if "ui_queue" not in st.session_state:
        st.session_state.ui_queue = queue.Queue()
    ui_queue = st.session_state.ui_queue

    # Placeholders (create each run but reference persisted objects)
    placeholder_status = st.empty()
    placeholder_ticks = st.empty()
    placeholder_chart = st.empty()

    # Load scrips & prepare WS symbol list (safe)
    try:
        scrips = ps_api.get_watchlist(selected_watchlist).get("values", [])
    except Exception as e:
        scrips = []
        st.warning(f"Could not load watchlist data: {e}")
    symbols_for_ws = [f"{s['exch']}|{s['token']}" for s in scrips if s.get("token")]

    # --- Figure init (only once) ---
    if st.session_state.get("live_fig") is None:
        fig0 = go.Figure()
        fig0.add_trace(go.Candlestick(
            x=[], open=[], high=[], low=[], close=[],
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
            name="Price"
        ))
        fig0.update_layout(
            xaxis=dict(rangeslider_visible=False, type="date"),
            yaxis=dict(fixedrange=False),
            dragmode="pan", hovermode="x unified",
            showlegend=False, template="plotly_dark", height=700,
            margin=dict(l=50, r=50, t=50, b=50),
            plot_bgcolor="black", paper_bgcolor="black", font=dict(color="white"),
            transition_duration=0
        )
        st.session_state.live_fig = fig0

    def ensure_main_trace():
        """Ensure the first candlestick trace exists for in-place updates."""
        fig = st.session_state.live_fig
        if not getattr(fig, "data", None):
            fig.add_trace(go.Candlestick(
                x=[], open=[], high=[], low=[], close=[],
                increasing_line_color="#26a69a",
                decreasing_line_color="#ef5350",
                name="Price"
            ))

    # --- Helper to load TPSeries history into session_state (one-time) ---
    def load_history_into_state(df_history):
        df_history = df_history.sort_index()
        st.session_state.ohlc_x = list(df_history.index)
        st.session_state.ohlc_o = list(df_history["open"].astype(float))
        st.session_state.ohlc_h = list(df_history["high"].astype(float))
        st.session_state.ohlc_l = list(df_history["low"].astype(float))
        st.session_state.ohlc_c = list(df_history["close"].astype(float))
        st.session_state.last_tp_dt = st.session_state.ohlc_x[-1] if st.session_state.ohlc_x else None

        # Replace main trace content (single update, prevents blink)
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

    # --- Tick -> candle update (called on each tick message) ---
    def update_last_candle_from_tick_local(tick, interval=1):
        try:
            ts = int(tick.get("ft") or tick.get("time") or 0)
            if ts == 0:
                return
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

            # ensure lists exist
            if not isinstance(st.session_state.get("ohlc_x"), list):
                st.session_state.ohlc_x = []
                st.session_state.ohlc_o = []
                st.session_state.ohlc_h = []
                st.session_state.ohlc_l = []
                st.session_state.ohlc_c = []

            # append or update last candle
            if not st.session_state.ohlc_x:
                st.session_state.ohlc_x = [candle_time]
                st.session_state.ohlc_o = [price]
                st.session_state.ohlc_h = [price]
                st.session_state.ohlc_l = [price]
                st.session_state.ohlc_c = [price]
                st.session_state.last_tp_dt = candle_time
            else:
                if st.session_state.last_tp_dt is None or candle_time > st.session_state.last_tp_dt:
                    st.session_state.ohlc_x.append(candle_time)
                    st.session_state.ohlc_o.append(price)
                    st.session_state.ohlc_h.append(price)
                    st.session_state.ohlc_l.append(price)
                    st.session_state.ohlc_c.append(price)
                    st.session_state.last_tp_dt = candle_time
                elif candle_time == st.session_state.ohlc_x[-1]:
                    st.session_state.ohlc_h[-1] = max(st.session_state.ohlc_h[-1], price)
                    st.session_state.ohlc_l[-1] = min(st.session_state.ohlc_l[-1], price)
                    st.session_state.ohlc_c[-1] = price
                else:
                    return

            # write into the existing candlestick trace (in-place)
            ensure_main_trace()
            trace = st.session_state.live_fig.data[0]
            trace.x = st.session_state.ohlc_x
            trace.open = st.session_state.ohlc_o
            trace.high = st.session_state.ohlc_h
            trace.low = st.session_state.ohlc_l
            trace.close = st.session_state.ohlc_c

        except Exception as e:
            placeholder_ticks.warning(f"⚠️ Candle update error: {e}")

    # --- WebSocket starter (thread target) ---
    def start_ws(symbols, ps_api, ui_queue):
        def on_tick_callback(tick):
            try:
                ui_queue.put(("tick", tick), block=False)
            except Exception:
                pass

        try:
            if not getattr(ps_api, "is_logged_in", lambda: False)():
                ui_queue.put(("ws_error", "Session not initialized (ws)"), block=False)
                return
            ws = ps_api.connect_websocket(symbols, on_tick=on_tick_callback, tick_file="ticks_tab5.log")
            # heartbeat thread inside WS
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
            try:
                ui_queue.put(("ws_error", str(e)), block=False)
            except Exception:
                pass

    # --- Preload TPSeries history and auto-start WS (safe) ---
    wl = st.session_state.selected_watchlist
    interval = selected_interval

    tpseries_results = []
    if ps_api.is_logged_in():
        try:
            tpseries_results = ps_api.fetch_tpseries_for_watchlist(wl, interval) or []
        except Exception as e:
            tpseries_results = []
            st.warning(f"TPSeries fetch error: {e}")
    else:
        tpseries_results = []
        st.warning("⚠️ Cannot fetch TPSeries: session not initialized")
        placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)

    # If we have TPSeries results, load first series into history (only once if not loaded)
    if tpseries_results:
        try:
            df = tpseries_results[0].get("data")
            if isinstance(df, pd.DataFrame) and "datetime" in df.columns:
                df = df.copy()
                df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
                df = df.dropna(subset=["datetime"])
                if not df.empty:
                    df["datetime"] = df["datetime"].dt.tz_localize("Asia/Kolkata", nonexistent="shift_forward", ambiguous="NaT")
                    df = df.dropna(subset=["datetime"]).set_index("datetime")
                    # numeric conversion + rename
                    for col in ["into", "inth", "intl", "intc", "intv", "open", "high", "low", "close", "volume"]:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                    if "into" in df.columns and "open" not in df.columns:
                        df = df.rename(columns={"into": "open", "inth": "high", "intl": "low", "intc": "close", "intv": "volume"})
                    df = df.dropna(subset=["open", "high", "low", "close"])

                    # only load history if our st.session_state.ohlc_x is empty (avoid re-loading every rerun)
                    if not st.session_state.ohlc_x:
                        load_history_into_state(df)
                        st.write(f"📊 Loaded TPSeries candles: {len(df)}")

                        # prepare holiday rangebreaks (naive datetimes for Plotly)
                        if "holiday_breaks" not in st.session_state:
                            full_holidays = pd.to_datetime([
                                "2025-02-26","2025-03-14","2025-03-31","2025-04-10","2025-04-14",
                                "2025-04-18","2025-05-01","2025-08-15","2025-08-27",
                                "2025-10-02","2025-10-21","2025-10-22","2025-11-05","2025-12-25"
                            ]).normalize()
                            holiday_breaks_naive = []
                            for h in full_holidays:
                                start = pd.Timestamp(h).tz_localize("Asia/Kolkata").replace(hour=9, minute=15)
                                end = pd.Timestamp(h).tz_localize("Asia/Kolkata").replace(hour=15, minute=30)
                                holiday_breaks_naive.append(dict(bounds=[start.to_pydatetime().replace(tzinfo=None),
                                                                        end.to_pydatetime().replace(tzinfo=None)]))
                            st.session_state.holiday_breaks = holiday_breaks_naive

                        # set xaxis rangebreaks (keeps layout consistent)
                        try:
                            st.session_state.live_fig.update_xaxes(rangebreaks=[
                                dict(bounds=["sat", "mon"]),
                                dict(bounds=[15.5, 9.25], pattern="hour"),
                                *st.session_state.get("holiday_breaks", [])
                            ])
                        except Exception:
                            pass

                        # Render initial chart
                        placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)

        except Exception as e:
            st.warning(f"TPSeries processing error: {e}")

    # --- Auto-start websocket (only once) ---
    # mark ws_started BEFORE starting thread so reruns don't spawn duplicates
    if symbols_for_ws and not st.session_state.get("ws_started", False):
        st.session_state.ws_started = True
        st.session_state.live_feed_flag["active"] = True
        st.session_state.symbols_for_ws = symbols_for_ws
        threading.Thread(target=start_ws, args=(symbols_for_ws, ps_api, ui_queue), daemon=True).start()
        st.info(f"📡 WebSocket thread launched for {len(symbols_for_ws)} symbols.")

    # --- Drain queue and apply live ticks to last candle (limited per rerun) ---
    if st.session_state.live_feed_flag.get("active", False):
        processed = 0
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
                    # allow retry later
                    st.session_state.ws_started = False

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

    try:
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
    except Exception:
        pass

    st.session_state.live_fig.update_yaxes(
        showgrid=True, gridwidth=0.5, gridcolor="gray", fixedrange=False
    )

    # --- Heavy plotting (TRM indicators) — only when candles changed or interval changed ---
    if st.session_state.ohlc_x and len(st.session_state.ohlc_x) > 20:
        df_live = pd.DataFrame({
            "datetime": pd.to_datetime(st.session_state.ohlc_x),
            "open": st.session_state.ohlc_o,
            "high": st.session_state.ohlc_h,
            "low": st.session_state.ohlc_l,
            "close": st.session_state.ohlc_c
        })

        # normalize tz then drop tz for plotly usage
        try:
            if df_live["datetime"].dt.tz is None:
                df_live["datetime"] = df_live["datetime"].dt.tz_localize("Asia/Kolkata")
            else:
                df_live["datetime"] = df_live["datetime"].dt.tz_convert("Asia/Kolkata")
            df_live["datetime"] = df_live["datetime"].apply(lambda x: x.replace(tzinfo=None))
        except Exception:
            df_live["datetime"] = pd.to_datetime(df_live["datetime"], errors="coerce").dropna()

        df_live = (df_live.drop_duplicates(subset="datetime").sort_values("datetime").reset_index(drop=True))

        # prepare rangebreaks if missing
        if "rangebreaks_obj" not in st.session_state:
            st.session_state.rangebreaks_obj = st.session_state.get("holiday_breaks", [])

        # cheap guard: only continue heavy charting if candles changed or interval changed
        _last_plot_key = st.session_state.get("_last_plot_key")
        curr_key = (len(st.session_state.ohlc_x), selected_interval)
        if _last_plot_key == curr_key:
            # nothing changed — early render the last plot and skip heavy plotting
            placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)
        else:
            st.session_state["_last_plot_key"] = curr_key
            # reuse existing fig but clear only traces (keeps layout)
            fig = st.session_state.live_fig
            fig.data = []   # clear traces to avoid duplicates
            settings = get_trm_settings()
            try:
                fig = plot_trm_chart(
                    df_live,
                    settings,
                    rangebreaks=st.session_state.get("rangebreaks_obj", []),
                    fig=fig,
                    show_macd_panel=True
                )
                st.session_state.live_fig = fig
                st.session_state.live_fig.update_xaxes(
                    showgrid=True, gridwidth=0.5, gridcolor="gray",
                    type="date", tickformat="%d-%m-%Y\n%H:%M", tickangle=0,
                    rangeslider_visible=False, rangebreaks=st.session_state.get("rangebreaks_obj", [])
                )
                placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)
            except Exception as e:
                # fallback: render basic live_fig
                placeholder_chart.plotly_chart(st.session_state.live_fig, use_container_width=True)
                placeholder_status.error(f"Plotting error: {e}")

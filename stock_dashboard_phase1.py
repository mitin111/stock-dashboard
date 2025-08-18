
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

# --- Tab 5: Strategy Engine ---
with tab5:
    st.subheader("📉 TPSeries Data Preview + Live Update")

    # === Normalize TPSeries API response ===
    def normalize_tpseries_data(raw_data):
        # Pehle check karo None ya empty list
        if raw_data is None or (isinstance(raw_data, list) and len(raw_data) == 0):
            return pd.DataFrame()

        # Agar response ek DataFrame hi hai, sidha return kar do
        if isinstance(raw_data, pd.DataFrame):
            return raw_data

        # Ab normal JSON list ko DataFrame me convert karte hain
        try:
            df = pd.DataFrame(raw_data)
        except Exception:
            return pd.DataFrame()

        # Required columns normalize karo
        if all(col in df.columns for col in ["time", "into", "inth", "intl", "intc", "v"]):
            df = df.rename(
                columns={
                    "time": "datetime",
                    "into": "open",
                    "inth": "high",
                    "intl": "low",
                    "intc": "close",
                    "v": "volume",
                }
            )
            df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
            df = df.dropna(subset=["datetime"])
            df = df.sort_values("datetime").reset_index(drop=True)

        return df

    # === Candlestick plotting ===
    def plot_tpseries_candles(df, symbol):
        # Ensure datetime type
        df['datetime'] = pd.to_datetime(df['datetime'])

        # Remove duplicates & sort
        df = df.drop_duplicates(subset=['datetime'])
        df = df.sort_values("datetime")

        # Filter market hours (09:15 to 15:30)
        df = df[
            (df['datetime'].dt.time >= pd.to_datetime("09:15").time()) &
            (df['datetime'].dt.time <= pd.to_datetime("15:30").time())
        ]

        # Single panel chart
        fig = make_subplots(rows=1, cols=1, shared_xaxes=True)

        # Candlestick trace
        fig.add_trace(go.Candlestick(
            x=df['datetime'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350',
            name='Price'
        ))

        # Layout settings
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

    # === Main logic ===
if "ps_api" not in st.session_state:
    st.warning("⚠️ Please login first using your API credentials.")
else:
    ps_api = st.session_state["ps_api"]

    wl_resp = ps_api.get_watchlists()
    if wl_resp.get("stat") == "Ok":
        watchlists = sorted(wl_resp["values"], key=int)
        selected_watchlist = st.selectbox("Select Watchlist", watchlists)
        selected_interval = st.selectbox(
            "Select Interval",
            ["1", "3", "5", "10", "15", "30", "60", "120", "240"]
        )

        # Step 1: Load watchlist
        if st.button("🔁 Load Watchlist"):
            wl_data = ps_api.get_watchlist(selected_watchlist)
            if wl_data.get("stat") == "Ok":
                st.session_state["watchlist_scrips"] = wl_data.get("values", [])
                st.success("✅ Watchlist loaded!")

        # Step 2: Pick one symbol for live chart
        if "watchlist_scrips" in st.session_state:
            scrips = st.session_state["watchlist_scrips"]
            symbol_options = {s["tsym"]: (s["exch"], s["token"]) for s in scrips}
            selected_symbol = st.selectbox("Select Symbol", list(symbol_options.keys()))

            if st.button("📊 Show Live Chart"):
                exch, token = symbol_options[selected_symbol]

                # Fetch initial candles via TPSeries
                raw_candles = ps_api.fetch_full_tpseries(
                    exch, token,
                    interval=selected_interval,
                    chunk_days=5,
                    max_days=60
                )
                df_candle = normalize_tpseries_data(raw_candles)

                if not df_candle.empty:
                    st.session_state["live_df"] = df_candle

                    chart_placeholder = st.empty()
                    fig = plot_tpseries_candles(df_candle, selected_symbol)
                    chart_placeholder.plotly_chart(fig, use_container_width=True)

                    # --- Live update from ticks ---
                    def on_tick(tick, df=df_candle, symbol=selected_symbol):
                        try:
                            price = float(tick["lp"])
                            ts = datetime.fromtimestamp(int(tick["ft"]) / 1000)  # tick ka time
                            minute = ts.replace(second=0, microsecond=0)  # 1-min bucket

                            if df.empty:
                                # agar empty hai to first candle create
                                new_candle = pd.DataFrame(
                                    [[minute, price, price, price, price, 1]],
                                    columns=["datetime", "open", "high", "low", "close", "volume"]
                                )
                                df = pd.concat([df, new_candle], ignore_index=True)
                            else:
                                last_candle_time = df.iloc[-1]["datetime"]

                                if last_candle_time == minute:
                                    # update existing candle
                                    df.loc[df.index[-1], "close"] = price
                                    df.loc[df.index[-1], "high"] = max(df.loc[df.index[-1], "high"], price)
                                    df.loc[df.index[-1], "low"] = min(df.loc[df.index[-1], "low"], price)
                                    df.loc[df.index[-1], "volume"] += 1
                                else:
                                    # ✅ naya minute → new candle create
                                    new_candle = pd.DataFrame(
                                        [[minute, price, price, price, price, 1]],
                                        columns=["datetime", "open", "high", "low", "close", "volume"]
                                    )
                                    df = pd.concat([df, new_candle], ignore_index=True)

                            # Save updated DataFrame back
                            st.session_state["live_df"] = df

                            # Redraw chart
                            fig = plot_tpseries_candles(df, symbol)
                            chart_placeholder.plotly_chart(fig, use_container_width=True)

                        except Exception as e:
                            print(f"Tick update error: {e}")

                    ps_api.on_tick = on_tick
                else:
                    st.warning("⚠️ No candle data found for this symbol")

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st
import json
import os

SETTINGS_FILE = "trm_settings.json"

# =========================
# Load / Save Settings
# =========================
def load_trm_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            try:
                settings = json.load(f)
            except:
                settings = {}
    else:
        settings = {}
    return settings

def save_trm_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

# =========================
# Streamlit Settings Panel
# =========================
if "trm_settings" not in st.session_state:
    st.session_state["trm_settings"] = load_trm_settings()
    
def get_trm_settings():
    # Load saved settings first
    saved = load_trm_settings()
    
    with st.expander("⚙️ TRM Settings (Manual Adjust)", expanded=False):
        long = st.number_input("TSI Long Length", 1, 900, saved.get("long", 25))
        short = st.number_input("TSI Short Length", 1, 200, saved.get("short", 5))
        signal = st.number_input("TSI Signal Length", 1, 200, saved.get("signal", 14))

        len_rsi = st.number_input("RSI Length", 1, 200, saved.get("len_rsi", 5))
        rsiBuyLevel = st.slider("RSI Buy Level", 0, 100, saved.get("rsiBuyLevel", 50))
        rsiSellLevel = st.slider("RSI Sell Level", 0, 100, saved.get("rsiSellLevel", 50))

        buyColor = st.color_picker("Buy Color", saved.get("buyColor", "#00FFFF"))
        sellColor = st.color_picker("Sell Color", saved.get("sellColor", "#FF00FF"))
        neutralColor = st.color_picker("Neutral Color", saved.get("neutralColor", "#808080"))

        pac_length = st.number_input("PAC Length", 1, 200, saved.get("pac_length", 34))
        use_heikin_ashi = st.checkbox("Use Heikin Ashi", saved.get("use_heikin_ashi", True))

        atr_fast_period = st.number_input("ATR Fast Period", 1, 200, saved.get("atr_fast_period", 5))
        atr_fast_mult = st.number_input("ATR Fast Multiplier", 0.1, 10.0, saved.get("atr_fast_mult", 0.5), 0.1)
        atr_slow_period = st.number_input("ATR Slow Period", 1, 200, saved.get("atr_slow_period", 10))
        atr_slow_mult = st.number_input("ATR Slow Multiplier", 0.1, 10.0, saved.get("atr_slow_mult", 3.0), 0.1)

        # 🔥 MACD Settings
        macd_fast = st.number_input("MACD Fast Length", 1, 200, saved.get("macd_fast", 12))
        macd_slow = st.number_input("MACD Slow Length", 1, 200, saved.get("macd_slow", 26))
        macd_signal = st.number_input("MACD Signal Length", 1, 200, saved.get("macd_signal", 9))

        show_info_panels = st.checkbox("Show Info Panels", saved.get("show_info_panels", True))

        settings = {
            "long": long, "short": short, "signal": signal,
            "len_rsi": len_rsi, "rsiBuyLevel": rsiBuyLevel, "rsiSellLevel": rsiSellLevel,
            "buyColor": buyColor, "sellColor": sellColor, "neutralColor": neutralColor,
            "pac_length": pac_length, "use_heikin_ashi": use_heikin_ashi,
            "atr_fast_period": atr_fast_period, "atr_fast_mult": atr_fast_mult,
            "atr_slow_period": atr_slow_period, "atr_slow_mult": atr_slow_mult,
            "macd_fast": macd_fast, "macd_slow": macd_slow, "macd_signal": macd_signal,
            "show_info_panels": show_info_panels
        }

        if st.button("💾 Save TRM Settings"):
            save_trm_settings(settings)
            st.session_state["trm_settings"] = settings  # 🔑 update memory
            st.success("✅ TRM Settings saved successfully!")

    return settings


# =========================
# Utility Functions
# =========================
def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def rsi(series, length=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.rolling(length).mean()
    ma_down = down.rolling(length).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

# =========================
# TRM Logic
# =========================
def calc_tkp_trm(df, settings):
    price = df["close"]
    pc = price.diff()

    first_smooth = ema(pc, settings["long"])
    double_smoothed_pc = ema(first_smooth, settings["short"])

    first_smooth_abs = ema(pc.abs(), settings["long"])
    double_smoothed_abs = ema(first_smooth_abs, settings["short"])

    tsi = 100 * (double_smoothed_pc / double_smoothed_abs)
    tsi_signal = ema(tsi, settings["signal"])
    rsi_vals = rsi(price, settings["len_rsi"])

    isBuy = (tsi > tsi_signal) & (rsi_vals > settings["rsiBuyLevel"])
    isSell = (tsi < tsi_signal) & (rsi_vals < settings["rsiSellLevel"])

    df["trm_signal"] = np.where(isBuy, "Buy",
                                np.where(isSell, "Sell", "Neutral"))

    df["barcolor"] = np.where(isBuy, settings["buyColor"],
                       np.where(isSell, settings["sellColor"], settings["neutralColor"]))
    df["tsi"] = tsi
    df["tsi_signal"] = tsi_signal
    df["rsi"] = rsi_vals
    return df

# =========================
# Yesterday High / Low
# =========================
def calc_yhl(df):
    df["date"] = df["datetime"].dt.date
    yhl = df.groupby("date").agg({"high": "max", "low": "min"}).shift(1)
    df = df.join(yhl, on="date", rsuffix="_yest")
    return df

# =========================
# PAC Channel
# =========================
def calc_pac(df, settings):
    close = df["close"]
    high = df["high"]
    low = df["low"]

    if settings["use_heikin_ashi"]:
        ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
        ha_open = (df["open"] + df["close"]) / 2
        ha_high = df[["high", "open", "close"]].max(axis=1)
        ha_low = df[["low", "open", "close"]].min(axis=1)
    else:
        ha_close, ha_open, ha_high, ha_low = close, df["open"], high, low

    df["pacC"] = ema(ha_close, settings["pac_length"])
    df["pacL"] = ema(ha_low, settings["pac_length"])
    df["pacU"] = ema(ha_high, settings["pac_length"])
    return df

# =========================
# ATR Trails
# =========================
def calc_atr(df, period):
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_atr_trails(df, settings):
    sc = df["close"]

    # --- Fast Trail ---
    sl1 = settings["atr_fast_mult"] * calc_atr(df, settings["atr_fast_period"])
    trail1 = pd.Series(index=df.index, dtype="float64")
    trail1.iloc[0] = sc.iloc[0]

    for i in range(1, len(df)):
        prev = trail1.iloc[i - 1]
        if sc.iloc[i] > prev and sc.iloc[i - 1] > prev:
            trail1.iloc[i] = max(prev, sc.iloc[i] - sl1.iloc[i])
        elif sc.iloc[i] < prev and sc.iloc[i - 1] < prev:
            trail1.iloc[i] = min(prev, sc.iloc[i] + sl1.iloc[i])
        elif sc.iloc[i] > prev:
            trail1.iloc[i] = sc.iloc[i] - sl1.iloc[i]
        else:
            trail1.iloc[i] = sc.iloc[i] + sl1.iloc[i]

    # --- Slow Trail ---
    sl2 = settings["atr_slow_mult"] * calc_atr(df, settings["atr_slow_period"])
    trail2 = pd.Series(index=df.index, dtype="float64")
    trail2.iloc[0] = sc.iloc[0]

    for i in range(1, len(df)):
        prev = trail2.iloc[i - 1]
        if sc.iloc[i] > prev and sc.iloc[i - 1] > prev:
            trail2.iloc[i] = max(prev, sc.iloc[i] - sl2.iloc[i])
        elif sc.iloc[i] < prev and sc.iloc[i - 1] < prev:
            trail2.iloc[i] = min(prev, sc.iloc[i] + sl2.iloc[i])
        elif sc.iloc[i] > prev:
            trail2.iloc[i] = sc.iloc[i] - sl2.iloc[i]
        else:
            trail2.iloc[i] = sc.iloc[i] + sl2.iloc[i]

    # Save results
    df["Trail1"] = trail1
    df["Trail2"] = trail2

    # Bullish/Bearish area shading condition
    df["Bull"] = (trail1 > trail2) & (sc > trail2) & (df["low"] > trail2)

    return df

# =========================
# MACD Calculation
# =========================
def calc_macd(df, settings):
    fast = settings.get("macd_fast", 12)
    slow = settings.get("macd_slow", 26)
    signal = settings.get("macd_signal", 9)

    exp1 = df["close"].ewm(span=fast, adjust=False).mean()
    exp2 = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = histogram
    return df


# =========================
# Wrapper for Streamlit / Plotly
# =========================
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import numpy as np

def add_trm_colored_candles(fig, df, settings, row=1, col=1):
    # TRM Colors
    buy_color = settings.get("buyColor", "#26a69a")
    sell_color = settings.get("sellColor", "#ef5350")
    neutral_color = settings.get("neutralColor", "#808080")

    # TRM signal color map
    colors = df["trm_signal"].map({
        "Buy": buy_color,
        "Sell": sell_color,
        "Neutral": neutral_color
    }).fillna(neutral_color)

    # Loop through bars
    for i in range(len(df)):
        o, h, l, c = df.loc[i, ["open", "high", "low", "close"]]
        t = df.loc[i, "datetime"]
        colr = colors.iloc[i]

        # Wick
        fig.add_trace(go.Scatter(
            x=[t, t], y=[l, h],
            mode="lines",
            line=dict(color=colr, width=1),
            showlegend=False
        ), row=row, col=col)

        # Body
        fig.add_trace(go.Scatter(
            x=[t, t],
            y=[o, c],
            mode="lines",
            line=dict(color=colr, width=6),
            showlegend=False
        ), row=row, col=col)


def plot_trm_chart(df, settings, rangebreaks=None, fig=None, show_macd_panel=True):
    df["datetime"] = pd.to_datetime(df["datetime"])

    # Indicators
    df = calc_tkp_trm(df, settings)
    df = calc_yhl(df)
    df = calc_pac(df, settings)
    df = calc_atr_trails(df, settings)
    df = calc_macd(df)

    # --- Create figure ---
    if show_macd_panel:
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.7, 0.3], vertical_spacing=0.08,
            subplot_titles=("Price + Indicators", "MACD")
        )
    else:
        fig = go.Figure()

    # --- Candles (TRM coloring) ---
    add_trm_colored_candles(fig, df, settings,
                            row=1 if show_macd_panel else None,
                            col=1 if show_macd_panel else None)

    # --- Overlays on price ---
    for col, name, color, width in [
        ("pacU", "PAC High", "#808080", 1),
        ("pacL", "PAC Low", "#808080", 1),
        ("pacC", "PAC Mid", "#00FFFF", 2),
        ("Trail1", "Fast Trail", "#FF00FF", 1),
        ("Trail2", "Slow Trail", "#00FFFF", 2),
        ("high_yest", "Yesterday High", "orange", 1),
        ("low_yest", "Yesterday Low", "teal", 1),
    ]:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df["datetime"], y=df[col], name=name,
                line=dict(color=color, width=width)
            ), row=1 if show_macd_panel else None, col=1 if show_macd_panel else None)

    # --- MACD (only if enabled) ---
    if show_macd_panel:
        fig.add_trace(go.Bar(
            x=df["datetime"], y=df["macd_hist"],
            marker_color=np.where(df["macd_hist"] >= 0, "#00FF00", "#FF0000"),
            name="MACD Histogram"
        ), row=2, col=1)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=df["macd"], name="MACD Line",
            line=dict(color="#00FFFF", width=1)
        ), row=2, col=1)
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=df["macd_signal"], name="Signal Line",
            line=dict(color="#FF00FF", dash="dot", width=1)
        ), row=2, col=1)

    # --- Layout ---
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="black",
        plot_bgcolor="black",
        font=dict(color="white"),
        height=800 if show_macd_panel else 600,
        hovermode="x unified",
        xaxis=dict(rangeslider_visible=False, rangebreaks=rangebreaks),
        dragmode="pan"
    )
    return fig



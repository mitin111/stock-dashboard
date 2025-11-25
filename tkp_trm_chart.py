import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st
import json
import os


# Always save/load TRM settings from the src folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "trm_settings.json")


# =========================
# Load / Save Settings
# =========================
def load_trm_settings_from_file():
    """Load TRM settings strictly from JSON file."""
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
    print("📝 Saving TRM file to:", SETTINGS_FILE)   # ✅ ADD
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

    print("✅ File written successfully:", os.path.exists(SETTINGS_FILE))  # ✅ ADD

# =========================
# Initialize session_state safely
# =========================
def ensure_trm_settings_loaded():
    if "trm_settings" not in st.session_state or not st.session_state["trm_settings"]:
        st.session_state["trm_settings"] = load_trm_settings_from_file()

# =========================
# Streamlit Settings Panel (UI only)
# =========================

def render_trm_settings_ui_body():
    current = st.session_state.get("trm_settings", {})

    long = st.number_input("TSI Long Length", 1, 900, current.get("long", 25), key="trm_long")
    short = st.number_input("TSI Short Length", 1, 200, current.get("short", 5), key="trm_short")
    signal = st.number_input("TSI Signal Length", 1, 200, current.get("signal", 14), key="trm_signal")

    len_rsi = st.number_input("RSI Length", 1, 200, current.get("len_rsi", 5), key="trm_rsi_len")
    rsiBuyLevel = st.slider("RSI Buy Level", 0, 100, current.get("rsiBuyLevel", 50), key="trm_rsi_buy")
    rsiSellLevel = st.slider("RSI Sell Level", 0, 100, current.get("rsiSellLevel", 50), key="trm_rsi_sell")

    buyColor = st.color_picker("Buy Color", current.get("buyColor", "#00FFFF"), key="trm_buy_color")
    sellColor = st.color_picker("Sell Color", current.get("sellColor", "#FF00FF"), key="trm_sell_color")
    neutralColor = st.color_picker("Neutral Color", current.get("neutralColor", "#808080"), key="trm_neutral_color")

    pac_length = st.number_input("PAC Length", 1, 200, current.get("pac_length", 34), key="trm_pac_len")
    use_heikin_ashi = st.checkbox("Use Heikin Ashi", current.get("use_heikin_ashi", True), key="trm_heikin")

    atr_fast_period = st.number_input("ATR Fast Period", 1, 200, current.get("atr_fast_period", 5), key="trm_atr_fast_p")
    atr_fast_mult = st.number_input("ATR Fast Multiplier", 0.1, 10.0, current.get("atr_fast_mult", 0.5), 0.1, key="trm_atr_fast_m")
    atr_slow_period = st.number_input("ATR Slow Period", 1, 200, current.get("atr_slow_period", 10), key="trm_atr_slow_p")
    atr_slow_mult = st.number_input("ATR Slow Multiplier", 0.1, 10.0, current.get("atr_slow_mult", 3.0), 0.1, key="trm_atr_slow_m")

    macd_fast = st.number_input("MACD Fast Length", 1, 1000, current.get("macd_fast", 12), key="trm_macd_fast")
    macd_slow = st.number_input("MACD Slow Length", 1, 1000, current.get("macd_slow", 26), key="trm_macd_slow")
    macd_signal = st.number_input("MACD Signal Length", 1, 200, current.get("macd_signal", 9), key="trm_macd_signal")

    show_info_panels = st.checkbox("Show Info Panels", current.get("show_info_panels", True), key="trm_show_panels")

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

    if st.button("💾 Save TRM Settings", key="trm_save_btn"):
        st.session_state["trm_settings"] = settings
        save_trm_settings(settings)
        st.success("✅ TRM Settings saved successfully!")

    return settings


# --- Prevent expander duplication safely ---
if "trm_settings_expander_rendered" not in st.session_state:
    st.session_state["trm_settings_expander_rendered"] = False

def render_trm_settings_once():
    """Render TRM Settings UI once per rerun"""
    ensure_trm_settings_loaded()   # ✅ FIX: load settings only when UI is drawn

    if not st.session_state["trm_settings_expander_rendered"]:
        with st.expander("⚙️ TRM Settings (Manual Adjust)", expanded=False):
            render_trm_settings_ui_body()
        st.session_state["trm_settings_expander_rendered"] = True
    else:
        st.markdown("### ⚙️ TRM Settings (Manual Adjust) *(Already loaded)*")

# ❌ REMOVE THIS LINE (was causing infinite rerun)
# render_trm_settings_once()

# =====================================================
# 🔹 Legacy Wrapper for Backward Compatibility
# =====================================================
def trm_settings_ui():
    """Legacy wrapper for backward compatibility (old imports)"""
    with st.expander("⚙️ TRM Settings (Manual Adjust)", expanded=False):
        return render_trm_settings_ui_body()


# =========================
# Background-safe access
# =========================
def get_trm_settings_safe():
    """Return TRM/MACD settings only if available, else None."""
    if "trm_settings" not in st.session_state or not st.session_state["trm_settings"]:
        return None
    return st.session_state["trm_settings"]

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
    # === Settings Validation (before indicators) ===
    required_keys = ["long", "short", "signal", "len_rsi",
                     "rsiBuyLevel", "rsiSellLevel",
                     "macd_fast", "macd_slow", "macd_signal"]

    if not settings:
        raise ValueError("❌ TRM/MACD settings missing! Please configure them in dashboard.")

    missing_keys = [k for k in required_keys if k not in settings]
    if missing_keys:
        raise ValueError(f"❌ TRM/MACD settings incomplete! Missing keys: {missing_keys}")

    print("🔹 Strategy settings loaded OK:", settings)

    # === Indicator Calculation ===
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
# Intraday Volatility Filter (Indicator)
# =========================
def calc_intraday_volatility_flag(df, threshold_single=1.3, threshold_two=2.0):
    """
    Returns a DataFrame column 'skip_due_to_intraday_vol' = True/False.
    Marks True if:
      (1) Any single candle > threshold_single % range
      (2) Two consecutive candles combined move ≥ threshold_two %
    """
    if df.empty:
        df["skip_due_to_intraday_vol"] = False
        return df

    try:
        df = df.copy()
        df["range_pct"] = ((df["high"] - df["low"]) / df["low"]) * 100

        # --- Single candle > threshold ---
        df["flag_single"] = df["range_pct"] >= threshold_single

        # --- Two-candle combined change ---
        df["close_change_pct"] = df["close"].pct_change() * 100
        df["two_candle_move"] = df["close_change_pct"].rolling(2).sum().abs()
        df["flag_two"] = df["two_candle_move"] >= threshold_two

        # --- Final flag ---
        df["skip_due_to_intraday_vol"] = df["flag_single"] | df["flag_two"]
        return df

    except Exception as e:
        print(f"⚠️ Intraday volatility calculation failed: {e}")
        df["skip_due_to_intraday_vol"] = False
        return df

# =========================
# Day Move Filter Indicator
# =========================
def calc_day_move_flag(df, threshold_pct=1.5):
    """
    Adds 'day_move_pct' and 'skip_due_to_day_move' columns.
    Marks True if today's price move from open exceeds threshold_pct (%).
    """
    if df.empty:
        df["day_move_pct"] = 0
        df["skip_due_to_day_move"] = False
        return df

    try:
        df = df.copy()
        df["date"] = df["datetime"].dt.date
        df["day_open"] = df.groupby("date")["open"].transform("first")
        df["day_move_pct"] = ((df["close"] - df["day_open"]) / df["day_open"]) * 100
        df["skip_due_to_day_move"] = df["day_move_pct"].abs() > threshold_pct
        return df

    except Exception as e:
        print(f"⚠️ Day move calculation failed: {e}")
        df["day_move_pct"] = 0
        df["skip_due_to_day_move"] = False
        return df

# ============================================================
# 🔹 Gap Move Filter (indicator)
# ============================================================
def calc_gap_move_flag(df: pd.DataFrame) -> pd.DataFrame:
    """
    Marks stocks that have >1.0% gap up/down between yesterday close and today's open.
    Adds columns: 'gap_pct' and 'skip_due_to_gap'
    """
    try:
        df = df.copy()
        df["gap_pct"] = 0.0
        df["skip_due_to_gap"] = False

        if len(df) < 2:
            return df

        # Get yesterday close and today's open (based on date)
        df["date"] = df["datetime"].dt.date
        unique_dates = df["date"].unique()
        if len(unique_dates) >= 2:
            today_date = unique_dates[-1]
            yesterday_date = unique_dates[-2]

            yclose = df.loc[df["date"] == yesterday_date, "close"].iloc[-1]
            oprice = df.loc[df["date"] == today_date, "open"].iloc[0]

            if yclose > 0:
                gap_pct = ((oprice - yclose) / yclose) * 100
                df.loc[df["date"] == today_date, "gap_pct"] = gap_pct
                if abs(gap_pct) > 1.0:
                    df.loc[df["date"] == today_date, "skip_due_to_gap"] = True

    except Exception as e:
        print(f"⚠️ Gap move calculation failed: {e}")

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

def add_volatility_panel(fig, df):
    """
    Add intraday volatility annotation on chart
    using formula: ((High - Low)/Low) * 100
    """
    if df.empty:
        return fig

    # 🔹 आज की तारीख
    latest_day = df["datetime"].iloc[-1].date()

    # 🔹 उसी दिन के candles filter करो
    day_data = df[df["datetime"].dt.date == latest_day]
    if day_data.empty:
        return fig

    # 🔹 High-Low निकालो
    day_high = day_data["high"].max()
    day_low = day_data["low"].min()

    # 🔹 Volatility %
    volatility = ((day_high - day_low) / day_low) * 100

    # 🔹 Chart पर annotation
    fig.add_annotation(
        text=f"📊 Day Volatility: {volatility:.2f}%",
        xref="paper", yref="paper",
        x=0.99, y=0.99, showarrow=False,
        font=dict(size=12, color="orange"),
        align="right", bgcolor="rgba(0,0,0,0.6)"
    )

    return fig

from dashboard_logic import load_qty_map

def suggested_qty_by_mapping(price, qty_map=None):
    """
    Decide quantity based on price range and mapping dict.
    Always requires a valid qty_map (from qty_map.json).
    If file missing/corrupt → return None (no trade).
    """
    if qty_map is None:
        qty_map = load_qty_map()

    # Agar file load hi nahi hui ya dict nahi mila
    if not isinstance(qty_map, dict) or not qty_map:
        return None   # ❌ no fallback default

    # --- Updated price ranges (1–100 ... 1000+)
    if 1 <= price <= 100:
        return qty_map.get("Q1")
    elif 101 <= price <= 150:
        return qty_map.get("Q2")
    elif 151 <= price <= 200:
        return qty_map.get("Q3")
    elif 201 <= price <= 250:
        return qty_map.get("Q4")
    elif 251 <= price <= 300:
        return qty_map.get("Q5")
    elif 301 <= price <= 350:
        return qty_map.get("Q6")
    elif 351 <= price <= 400:
        return qty_map.get("Q7")
    elif 401 <= price <= 450:
        return qty_map.get("Q8")
    elif 451 <= price <= 500:
        return qty_map.get("Q9")
    elif 501 <= price <= 550:
        return qty_map.get("Q10")
    elif 551 <= price <= 600:
        return qty_map.get("Q11")
    elif 601 <= price <= 650:
        return qty_map.get("Q12")
    elif 651 <= price <= 700:
        return qty_map.get("Q13")
    elif 701 <= price <= 750:
        return qty_map.get("Q14")
    elif 751 <= price <= 800:
        return qty_map.get("Q15")
    elif 801 <= price <= 850:
        return qty_map.get("Q16")
    elif 851 <= price <= 900:
        return qty_map.get("Q17")
    elif 901 <= price <= 950:
        return qty_map.get("Q18")
    elif 951 <= price <= 1000:
        return qty_map.get("Q19")
    elif price > 1000:
        return qty_map.get("Q20")
    else:
        return None   # ❌ invalid range → no qty


# =========================
# Wrapper for Streamlit / Plotly
# =========================
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import numpy as np
import pandas as pd

# =========================
# Optimized TRM Candles
# =========================
def add_trm_colored_candles(fig, df, settings, row=1, col=1, max_bars=1500):
    """
    TRM-colored candlesticks (stable with indicators)
    - Wick = one trace (gray)
    - Body = one scatter per candle (with TRM color)
    """

    if len(df) > max_bars:
        df = df.iloc[-max_bars:]

    # --- Color settings ---
    buy_color = settings.get("buyColor", "#26a69a")
    sell_color = settings.get("sellColor", "#ef5350")
    neutral_color = settings.get("neutralColor", "#808080")

    # ------------------------
    # Wick trace (all gray)
    # ------------------------
    wick_x, wick_y = [], []
    for t, l, h in zip(df["datetime"], df["low"], df["high"]):
        wick_x += [t, t, None]
        wick_y += [l, h, None]

    fig.add_trace(go.Scatter(
        x=wick_x, y=wick_y,
        mode="lines",
        line=dict(color="lightgray", width=1),
        showlegend=False
    ), row=row, col=col)

    # ------------------------
    # Body traces (one per candle)
    # ------------------------
    for t, o, c, sig in zip(df["datetime"], df["open"], df["close"], df["trm_signal"]):
        if sig == "Buy":
            colr = buy_color
        elif sig == "Sell":
            colr = sell_color
        else:
            colr = neutral_color

        fig.add_trace(go.Scatter(
            x=[t, t],
            y=[o, c],
            mode="lines",
            line=dict(color=colr, width=6),
            showlegend=False
        ), row=row, col=col)

# =========================
# Main TRM Chart
# =========================
def plot_trm_chart(df, settings, rangebreaks=None, fig=None, show_macd_panel=True):
    # === Settings Validation ===
    required_keys = ["long", "short", "signal", "len_rsi",
                     "rsiBuyLevel", "rsiSellLevel",
                     "macd_fast", "macd_slow", "macd_signal"]

    if not settings:
        raise ValueError("❌ TRM/MACD settings missing! Please configure them in dashboard.")

    missing_keys = [k for k in required_keys if k not in settings]
    if missing_keys:
        raise ValueError(f"❌ TRM/MACD settings incomplete! Missing: {missing_keys}")

    print("🔹 Strategy settings loaded OK:", settings)

    # === Indicator calculations ===
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = calc_tkp_trm(df, settings)
    df = calc_yhl(df)
    df = calc_pac(df, settings)
    df = calc_atr_trails(df, settings)
    df = calc_macd(df, settings)   # ✅ MACD added
    df = calc_intraday_volatility_flag(df)   # ✅ add this
    df = calc_gap_move_flag(df)
    df = calc_intraday_volatility_flag(df)

    # --- Create figure ---
    if show_macd_panel:
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.7, 0.3], vertical_spacing=0.08,
            subplot_titles=("Price + Indicators", "MACD"),
            specs=[[{"secondary_y": False}], [{"secondary_y": False}]]
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
        # Histogram
        fig.add_trace(
            go.Bar(
                x=df["datetime"],
                y=df["macd_hist"],
                marker_color=np.where(df["macd_hist"] >= 0, "#00FF00", "#FF0000"),
                name="MACD Histogram"
            ),
            row=2, col=1, secondary_y=False
        )

        # MACD Line
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=df["macd"],
                name="MACD Line",
                line=dict(color="#00FFFF", width=1)
            ),
            row=2, col=1, secondary_y=False
        )

        # Signal Line
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=df["macd_signal"],
                name="Signal Line",
                line=dict(color="#FF00FF", dash="dot", width=1)
            ),
            row=2, col=1, secondary_y=False
        )

    # --- Force separate Y-axes for row-1 (price) and row-2 (MACD)
    fig.update_yaxes(
        title_text="Price",
        row=1, col=1,
        rangemode="normal",
        showgrid=True,
        fixedrange=False
    )

    fig.update_yaxes(
        title_text="MACD",
        row=2, col=1,
        rangemode="tozero",
        showgrid=True,
        zeroline=True,
        zerolinecolor="white",
        zerolinewidth=1,
        fixedrange=False
    )


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
    fig = add_volatility_panel(fig, df)
    
    return fig
























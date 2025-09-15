import pandas as pd
import numpy as np
import plotly.graph_objects as go

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

    # Fast trail
    sl1 = settings["atr_fast_mult"] * calc_atr(df, settings["atr_fast_period"])
    trail1 = pd.Series(index=df.index, dtype="float64")
    trail1.iloc[0] = sc.iloc[0]
    for i in range(1, len(df)):
        if sc.iloc[i] > trail1.iloc[i-1]:
            trail1.iloc[i] = sc.iloc[i] - sl1.iloc[i]
        else:
            trail1.iloc[i] = sc.iloc[i] + sl1.iloc[i]

    # Slow trail
    sl2 = settings["atr_slow_mult"] * calc_atr(df, settings["atr_slow_period"])
    trail2 = pd.Series(index=df.index, dtype="float64")
    trail2.iloc[0] = sc.iloc[0]
    for i in range(1, len(df)):
        if sc.iloc[i] > trail2.iloc[i-1]:
            trail2.iloc[i] = sc.iloc[i] - sl2.iloc[i]
        else:
            trail2.iloc[i] = sc.iloc[i] + sl2.iloc[i]

    df["Trail1"] = trail1
    df["Trail2"] = trail2
    df["Bull"] = (trail1 > trail2) & (sc > trail2) & (df["low"] > trail2)
    return df

# =========================
# Wrapper for Streamlit / Plotly
# =========================
def plot_trm_chart(df, settings=None):
    if settings is None:
        settings = {
            "long": 25, "short": 5, "signal": 14,
            "len_rsi": 5, "rsiBuyLevel": 50, "rsiSellLevel": 50,
            "buyColor": "aqua", "sellColor": "fuchsia", "neutralColor": "gray",
            "pac_length": 34, "use_heikin_ashi": True,
            "atr_fast_period": 5, "atr_fast_mult": 0.5,
            "atr_slow_period": 10, "atr_slow_mult": 3.0,
            "show_info_panels": True
        }

    if "datetime" not in df.columns:
        if "time" in df.columns:
            df = df.rename(columns={"time": "datetime"})
        elif "ts" in df.columns:
            df = df.rename(columns={"ts": "datetime"})
        else:
            raise ValueError(f"[plot_trm_chart] Missing datetime column. Found: {df.columns}")

    df["datetime"] = pd.to_datetime(df["datetime"])

    # === Calculations ===
    df = calc_tkp_trm(df, settings)
    df = calc_yhl(df)
    df = calc_pac(df, settings)
    df = calc_atr_trails(df, settings)

    # === Traces ===
    traces = []
    traces.append(go.Candlestick(
        x=df["datetime"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], showlegend=False
    ))
    traces.append(go.Scatter(x=df["datetime"], y=df["high_yest"],
                             name="Yesterday High", line=dict(color="orange", width=1)))
    traces.append(go.Scatter(x=df["datetime"], y=df["low_yest"],
                             name="Yesterday Low", line=dict(color="teal", width=1)))
    traces.append(go.Scatter(x=df["datetime"], y=df["pacU"],
                             name="PAC High", line=dict(color="gray", width=1)))
    traces.append(go.Scatter(x=df["datetime"], y=df["pacL"],
                             name="PAC Low", line=dict(color="gray", width=1)))
    traces.append(go.Scatter(x=df["datetime"], y=df["pacC"],
                             name="PAC Close", line=dict(color="red", width=2)))
    traces.append(go.Scatter(x=df["datetime"], y=df["Trail1"],
                             name="Fast Trail", line=dict(color="blue", width=1)))
    traces.append(go.Scatter(x=df["datetime"], y=df["Trail2"],
                             name="Slow Trail", line=dict(color="green", width=2)))
    return traces

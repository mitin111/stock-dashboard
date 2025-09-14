# tkp_trm_chart.py
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import pandas_ta as ta

def plot_trm_chart(df):
    # =============================
    # TKP TRM (TSI + RSI) calculation
    # =============================
    long_len, short_len, sig_len, rsi_len = 25, 5, 14, 5
    rsi_buy, rsi_sell = 50, 50

    # TSI
    pc = df["close"].diff()
    first_smooth = pc.ewm(span=long_len, adjust=False).mean()
    double_smoothed_pc = first_smooth.ewm(span=short_len, adjust=False).mean()
    first_smooth_abs = pc.abs().ewm(span=long_len, adjust=False).mean()
    double_smoothed_abs_pc = first_smooth_abs.ewm(span=short_len, adjust=False).mean()
    df["tsi"] = 100 * (double_smoothed_pc / double_smoothed_abs_pc)
    df["tsi_signal"] = df["tsi"].ewm(span=sig_len, adjust=False).mean()

    # RSI
    rsi = ta.rsi(df["close"], length=rsi_len)
    df["rsi"] = rsi

    # Buy/Sell Conditions
    df["isBuy"] = (df["tsi"] > df["tsi_signal"]) & (df["rsi"] > rsi_buy)
    df["isSell"] = (df["tsi"] < df["tsi_signal"]) & (df["rsi"] < rsi_sell)

    # Bar colors
    def get_color(row):
        if row["isBuy"]:
            return "aqua"
        elif row["isSell"]:
            return "fuchsia"
        else:
            return "gray"
    df["barcolor"] = df.apply(get_color, axis=1)

    # =============================
    # Yesterday High / Low
    # =============================
    df["date"] = df.index.date
    yhl = df.groupby("date")["high"].max().shift(1)
    yll = df.groupby("date")["low"].min().shift(1)
    df["yesterdayHigh"] = df["date"].map(yhl)
    df["yesterdayLow"] = df["date"].map(yll)

    # =============================
    # PAC EMA
    # =============================
    HiLoLen = 34
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    df["pacC"] = ha_close.ewm(span=HiLoLen).mean()
    df["pacU"] = df["high"].ewm(span=HiLoLen).mean()
    df["pacL"] = df["low"].ewm(span=HiLoLen).mean()

    # =============================
    # ATR Trailing Stops
    # =============================
    atr_fast = ta.atr(df["high"], df["low"], df["close"], length=5)
    atr_slow = ta.atr(df["high"], df["low"], df["close"], length=10)

    AF1, AF2 = 0.5, 3.0
    df["Trail1"] = df["close"] - AF1 * atr_fast
    df["Trail2"] = df["close"] - AF2 * atr_slow

    # Bull/Bear shading
    df["Bull"] = df["Trail1"] > df["Trail2"]

    # =============================
    # PLOT
    # =============================
    fig = go.Figure()

    # Candles with TRM color
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        increasing_line_color="aqua",
        decreasing_line_color="fuchsia",
        showlegend=False
    ))

    # Yesterday High/Low
    fig.add_trace(go.Scatter(x=df.index, y=df["yesterdayHigh"], mode="lines", line=dict(color="orange", width=1), name="Yesterday High"))
    fig.add_trace(go.Scatter(x=df.index, y=df["yesterdayLow"], mode="lines", line=dict(color="teal", width=1), name="Yesterday Low"))

    # PAC
    fig.add_trace(go.Scatter(x=df.index, y=df["pacC"], mode="lines", line=dict(color="red", width=2), name="PAC Close"))
    fig.add_trace(go.Scatter(x=df.index, y=df["pacU"], mode="lines", line=dict(color="gray", width=1), name="PAC Upper"))
    fig.add_trace(go.Scatter(x=df.index, y=df["pacL"], mode="lines", line=dict(color="gray", width=1), name="PAC Lower"))

    # Trails
    fig.add_trace(go.Scatter(x=df.index, y=df["Trail1"], mode="lines", line=dict(color="blue", width=1), name="Fast Trail"))
    fig.add_trace(go.Scatter(x=df.index, y=df["Trail2"], mode="lines", line=dict(color="green", width=1), name="Slow Trail"))

    fig.update_layout(title="TKP TRM + YHL + PAC + ATR Trails (Python)", xaxis_rangeslider_visible=False)

    return fig

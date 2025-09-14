
  # tkp_trm_chart.py
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange

def plot_trm_chart(df):
    df = df.copy()

    # --- Yesterday High / Low (aligned properly) ---
    daily_high = df["high"].resample("1D").max().shift(1)
    daily_low = df["low"].resample("1D").min().shift(1)
    df["yesterdayHigh"] = df.index.normalize().map(daily_high)
    df["yesterdayLow"] = df.index.normalize().map(daily_low)

    # --- PAC EMA ---
    HiLoLen = 34
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    df["pacC"] = EMAIndicator(ha_close, window=HiLoLen).ema_indicator()
    df["pacU"] = EMAIndicator(df["high"], window=HiLoLen).ema_indicator()
    df["pacL"] = EMAIndicator(df["low"], window=HiLoLen).ema_indicator()

    # --- ATR Trails (shifted to current bar properly) ---
    atr_fast = AverageTrueRange(df["high"], df["low"], df["close"], window=5).average_true_range()
    atr_slow = AverageTrueRange(df["high"], df["low"], df["close"], window=10).average_true_range()
    AF1, AF2 = 0.5, 3.0
    df["Trail1"] = df["close"] - AF1 * atr_fast.shift(1)
    df["Trail2"] = df["close"] - AF2 * atr_slow.shift(1)

    # --- Chart ---
    fig = go.Figure()

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="Price",
        increasing_line_color="green",
        decreasing_line_color="red",
        showlegend=False
    ))

    # Yesterday High/Low
    fig.add_trace(go.Scatter(x=df.index, y=df["yesterdayHigh"], mode="lines",
                             line=dict(color="orange", width=1, dash="dot"), name="Yesterday High"))
    fig.add_trace(go.Scatter(x=df.index, y=df["yesterdayLow"], mode="lines",
                             line=dict(color="teal", width=1, dash="dot"), name="Yesterday Low"))

    # PAC
    fig.add_trace(go.Scatter(x=df.index, y=df["pacC"], mode="lines", line=dict(color="blue", width=2), name="PAC Close"))
    fig.add_trace(go.Scatter(x=df.index, y=df["pacU"], mode="lines", line=dict(color="gray", width=1), name="PAC Upper"))
    fig.add_trace(go.Scatter(x=df.index, y=df["pacL"], mode="lines", line=dict(color="gray", width=1), name="PAC Lower"))

    # ATR Trails
    fig.add_trace(go.Scatter(x=df.index, y=df["Trail1"], mode="lines", line=dict(color="purple", width=1), name="Fast Trail"))
    fig.add_trace(go.Scatter(x=df.index, y=df["Trail2"], mode="lines", line=dict(color="brown", width=1), name="Slow Trail"))

    fig.update_layout(
        title="TKP TRM + YHL + PAC + ATR Trails (Python)",
        xaxis_rangeslider_visible=False,
        template="plotly_white"
    )

    return fig



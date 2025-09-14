
  # tkp_trm_chart.py
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange

def plot_trm_chart(df):
    df = df.copy()
    
    # =============================
    # TSI (double EMA)
    # =============================
    long_len, short_len, sig_len = 25, 5, 14
    pc = df["close"].diff()
    ema1 = pc.ewm(span=long_len, adjust=False).mean()
    ema2 = ema1.ewm(span=short_len, adjust=False).mean()
    abs_pc = pc.abs()
    ema1_abs = abs_pc.ewm(span=long_len, adjust=False).mean()
    ema2_abs = ema1_abs.ewm(span=short_len, adjust=False).mean()
    df["tsi"] = 100 * (ema2 / ema2_abs)
    df["tsi_signal"] = df["tsi"].ewm(span=sig_len, adjust=False).mean()
    
    # =============================
    # RSI
    # =============================
    df["rsi"] = RSIIndicator(close=df["close"], window=5).rsi()
    
    # =============================
    # Buy/Sell conditions
    # =============================
    df["isBuy"] = (df["tsi"] > df["tsi_signal"]) & (df["rsi"] > 50)
    df["isSell"] = (df["tsi"] < df["tsi_signal"]) & (df["rsi"] < 50)
    df["barcolor"] = np.where(df["isBuy"], "aqua", np.where(df["isSell"], "fuchsia", "gray"))
    
    # =============================
    # Yesterday High / Low
    # =============================
    df["date"] = df.index.floor("D")
    yhl = df.groupby("date")["high"].max().shift(1)
    yll = df.groupby("date")["low"].min().shift(1)
    df["yesterdayHigh"] = df["date"].map(yhl)
    df["yesterdayLow"] = df["date"].map(yll)
    
    # =============================
    # PAC EMA
    # =============================
    HiLoLen = 34
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    df["pacC"] = EMAIndicator(ha_close, window=HiLoLen).ema_indicator()
    df["pacU"] = EMAIndicator(df["high"], window=HiLoLen).ema_indicator()
    df["pacL"] = EMAIndicator(df["low"], window=HiLoLen).ema_indicator()
    
    # =============================
    # ATR Trailing Stops
    # =============================
    atr_fast = AverageTrueRange(df["high"], df["low"], df["close"], window=5).average_true_range()
    atr_slow = AverageTrueRange(df["high"], df["low"], df["close"], window=10).average_true_range()
    AF1, AF2 = 0.5, 3.0
    df["Trail1"] = df["close"] - AF1 * atr_fast
    df["Trail2"] = df["close"] - AF2 * atr_slow
    df["Bull"] = df["Trail1"] > df["Trail2"]
    
    # =============================
    # PLOT
    # =============================
    fig = go.Figure()
    
    # Candlestick with TRM coloring
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
    
    # ATR Trails
    fig.add_trace(go.Scatter(x=df.index, y=df["Trail1"], mode="lines", line=dict(color="blue", width=1), name="Fast Trail"))
    fig.add_trace(go.Scatter(x=df.index, y=df["Trail2"], mode="lines", line=dict(color="green", width=1), name="Slow Trail"))
    
    fig.update_layout(title="TKP TRM + YHL + PAC + ATR Trails (Python)", xaxis_rangeslider_visible=False)
    
    return fig



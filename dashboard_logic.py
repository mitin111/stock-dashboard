# dashboard_logic.py

import os
import json
from dotenv import load_dotenv
from datetime import datetime, time

SETTINGS_FILE = "dashboard_settings.json"

# === Load settings from file
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {
        "master_auto": True,
        "auto_buy": True,
        "auto_sell": True
    }

# === Save settings to file
def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

# === Load ProStocks credentials from environment
def load_credentials():
    load_dotenv()
    return {
        "uid": os.getenv("PROSTOCKS_USER_ID", ""),
        "pwd": os.getenv("PROSTOCKS_PASSWORD", ""),
        "factor2": os.getenv("PROSTOCKS_FACTOR2", ""),
        "vc": os.getenv("PROSTOCKS_VENDOR_CODE", ""),
        "api_key": os.getenv("PROSTOCKS_API_KEY", ""),
        "imei": os.getenv("PROSTOCKS_MAC", "MAC123456"),
        "base_url": os.getenv("PROSTOCKS_BASE_URL", "https://starapi.prostocks.com/NorenWClientTP"),
        "apkversion": os.getenv("PROSTOCKS_APK_VERSION", "1.0.0"),
    }

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
            # Convert string times to datetime.time
            for k in ["trading_start", "trading_end", "cutoff_time", "auto_exit_time"]:
                if k in data:
                    data[k] = datetime.strptime(data[k], "%H:%M").time()
            return data
    return {
        "master_auto": True,
        "auto_buy": True,
        "auto_sell": True,
        "trading_start": time(9, 15),
        "trading_end": time(15, 15),
        "cutoff_time": time(14, 50),
        "auto_exit_time": time(15, 12)
    }

def calculate_macd(df, fast_length=12, slow_length=26, signal_length=9, 
                   src_col='Close', 
                   ma_type_macd='EMA', 
                   ma_type_signal='EMA'):
    df = df.copy()
    src = df[src_col]

    def ma(series, length, method):
        return series.ewm(span=length, adjust=False).mean() if method == 'EMA' else series.rolling(window=length).mean()

    fast_ma = ma(src, fast_length, ma_type_macd)
    slow_ma = ma(src, slow_length, ma_type_macd)
    df['MACD'] = fast_ma - slow_ma
    df['Signal'] = ma(df['MACD'], signal_length, ma_type_signal)
    df['Histogram'] = df['MACD'] - df['Signal']

    return df[['MACD', 'Signal', 'Histogram']]


def calculate_heikin_ashi(df):
    ha_df = df.copy()
    ha_df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4

    ha_open = [(df['Open'].iloc[0] + df['Close'].iloc[0]) / 2]
    for i in range(1, len(df)):
        ha_open.append((ha_open[i - 1] + ha_df['HA_Close'].iloc[i - 1]) / 2)

    ha_df['HA_Open'] = ha_open
    ha_df['HA_High'] = ha_df[['High', 'HA_Open', 'HA_Close']].max(axis=1)
    ha_df['HA_Low'] = ha_df[['Low', 'HA_Open', 'HA_Close']].min(axis=1)

    return ha_df
macd_df = calculate_macd(
    data,
    fast_length=macd_fast,
    slow_length=macd_slow,
    signal_length=macd_signal,
    src_col=macd_source.lower().capitalize(),  # e.g., "Close"
    ma_type_macd=macd_ma_type,
    ma_type_signal=macd_ma_type  # or separate config for signal MA
)

macd_hist = macd_df["Histogram"].iloc[-1]

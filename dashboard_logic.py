# dashboard_logic.py

# dashboard_logic.py

import os
import json
from dotenv import load_dotenv
from datetime import datetime, time

SETTINGS_FILE = "dashboard_settings.json"
QTY_MAP_FILE = "qty_map.json"

# === Load general dashboard settings (auto buy/sell, timings etc.)
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

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

# === Qty Map (Q1..Q6)
def save_qty_map(qty_map: dict):
    """Save qty_map to JSON file for persistence."""
    with open(QTY_MAP_FILE, "w") as f:
        json.dump(qty_map, f)

def load_qty_map() -> dict:
    """Load qty_map from JSON file if exists, else defaults."""
    if os.path.exists(QTY_MAP_FILE):
        try:
            with open(QTY_MAP_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    # default fallback
    return {"Q1": 10, "Q2": 20, "Q3": 30, "Q4": 40, "Q5": 50, "Q6": 60}

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

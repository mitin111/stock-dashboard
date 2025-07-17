# prostocks_data.py

import logging
from prostocks_connector import login_ps  # ✅ This should return a logged-in API object
from api_helper import NorenApiPy

# === Setup Logging ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ✅ Initialize and login
try:
    ps_api = login_ps()
    logging.info("✅ ProStocks API session initialized.")
except Exception as e:
    logging.error(f"❌ ProStocks login failed: {e}")
    raise

# === Get Token for Symbol ===
def get_token(symbol: str) -> str:
    try:
        scrip = ps_api.searchscrip(exchange="NSE", searchtext=symbol)
        token = scrip["values"][0]["token"]
        return token
    except Exception as e:
        logging.error(f"❌ Error getting token for {symbol}: {e}")
        return None

# === Get LTP for a Symbol ===
def get_ltp(symbol: str):
    try:
        token = get_token(symbol)
        if not token:
            return None
        quote = ps_api.get_quotes(exchange="NSE", token=token)
        ltp = float(quote["lp"])
        logging.info(f"✅ LTP for {symbol}: ₹{ltp}")
        return ltp
    except Exception as e:
        logging.error(f"❌ Error getting LTP for {symbol}: {e}")
        return None

# === Get Candlestick Data ===
def get_candles(symbol: str, interval: str = "5", days: int = 1):
    try:
        token = get_token(symbol)
        if not token:
            return None
        candles = ps_api.get_time_price_series(exchange="NSE", token=token, interval=interval, days=days)
        logging.info(f"✅ Candle data fetched for {symbol}")
        return candles
    except Exception as e:
        logging.error(f"❌ Error getting candles for {symbol}: {e}")
        return None

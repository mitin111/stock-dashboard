
import hashlib
import requests
import json
import os

class ProStocksAPI:
    def __init__(self, userid, password_plain, factor2, vc, api_key, imei, base_url, apkversion="1.0.0"):
        self.userid = userid
        self.password_plain = password_plain
        self.factor2 = factor2
        self.vc = vc
        self.api_key = api_key
        self.imei = imei
        self.base_url = base_url.rstrip("/")
        self.apkversion = apkversion
        self.session_token = None
        self.session = requests.Session()
        self.headers = {
            "Content-Type": "text/plain"
        }

    def sha256(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    def login(self):
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_raw = f"{self.userid}|{self.api_key}"
        appkey_hash = self.sha256(appkey_raw)

        print("📎 App Key Raw:", appkey_raw)
        print("🔐 Hashed App Key:", appkey_hash)

        payload = {
            "uid": self.userid,
            "pwd": pwd_hash,
            "factor2": self.factor2,
            "vc": self.vc,
            "appkey": appkey_hash,
            "imei": self.imei,
            "apkversion": self.apkversion,
            "source": "API"
        }

        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            response = self.session.post(
                url,
                data=raw_data,
                headers=self.headers,
                timeout=10
            )
            print("🔁 Response Code:", response.status_code)
            print("📨 Response Body:", response.text)

            if response.status_code == 200:
                data = response.json()
                if data.get("stat") == "Ok":
                    self.session_token = data["susertoken"]
                    self.headers["Authorization"] = self.session_token
                    print("✅ Login Success!")
                    return True, self.session_token
                else:
                    return False, data.get("emsg", "Unknown login error")
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"RequestException: {e}"

    # 🔍 Add below login
    import urllib.parse  # ⬅️ At top of file if not already

def get_quotes(self, symbol, exchange="NSE"):
    """
    Fetches live market data (LTP, OHLC, etc.) for the given symbol.
    Format: symbol should be like "LTFOODS-EQ"
    """
    try:
        tsym = urllib.parse.quote_plus(symbol.upper())  # ✅ Required format
        payload = {
            "uid": self.userid,
            "exch": exchange,
            "tsym": tsym,
        }
        url = f"{self.base_url}/QuickQuote"
        response = self.session.get(url, params=payload, headers=self.headers)
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as e:
        print(f"❌ Error in get_quotes for {symbol}: {e}")
        return None

    # 💰 Add below get_quotes
    
    def get_ltp(self, symbol, exchange="NSE"):
        """
        Returns the Last Traded Price (LTP) of the given symbol.
        """
        try:
            quote = self.get_quotes(symbol, exchange)
            return float(quote.get("lp", 0)) if quote else None
        except Exception as e:
            print(f"❌ Error in get_ltp for {symbol}: {e}")
            return None

       # 📊 Add below get_ltp
    
    def get_candles(self, token, interval="5", exchange="NSE", days=1, limit=None):
        """
        Fetches historical OHLC candle data for the given token.

        token: Instrument token (not the symbol like "RELIANCE-EQ")
        interval: "1", "3", "5", "15", "30", "60", "D"
        days: Number of days to fetch
        limit: Optional max number of candles to return
        """
        try:
            payload = {
                "uid": self.userid,
                "exch": exchange,
                "token": token,
                "interval": interval,
                "days": str(days)
            }
            url = f"{self.base_url}/GetCandleData"
            response = self.session.get(url, params=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()

            if data.get("stat") == "Ok":
                candles = data.get("candles", [])
                if limit:
                    return candles[-limit:]
                return candles
            else:
                print(f"❌ get_candles error: {data.get('emsg', 'Unknown error')}")
                return []
        except Exception as e:
            print(f"❌ Exception in get_candles for {token}: {e}")
            return []


# ✅ Wrapper for reuse
def login_ps(user_id=None, password=None, factor2=None, app_key=None):
    user_id = user_id or os.getenv("PROSTOCKS_USER_ID")
    password = password or os.getenv("PROSTOCKS_PASSWORD")
    factor2 = factor2 or os.getenv("PROSTOCKS_FACTOR2")
    vc = os.getenv("PROSTOCKS_VENDOR_CODE", user_id)
    imei = os.getenv("PROSTOCKS_MAC", "MAC123456")
    app_key = app_key or os.getenv("PROSTOCKS_API_KEY")
    base_url = os.getenv("PROSTOCKS_BASE_URL", "https://starapiuat.prostocks.com/NorenWClientTP")
    apkversion = os.getenv("PROSTOCKS_APKVERSION", "1.0.0")

    if not all([user_id, password, factor2, app_key]):
        print("❌ Missing login credentials.")
        return None

    try:
        print("📶 Logging into ProStocks API...")
        api = ProStocksAPI(user_id, password, factor2, vc, app_key, imei, base_url, apkversion)
        success, token = api.login()
        if success:
            print("✅ Login successful!")
            return api
        else:
            print("❌ Login failed:", token)
            return None
    except Exception as e:
        print("❌ Login Exception:", e)
        return None

        

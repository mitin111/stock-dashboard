
import requests
import hashlib
import json
import os
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

class ProStocksAPI:
    def __init__(
        self,
        userid=None,
        password_plain=None,
        vc=None,
        api_key=None,
        imei=None,
        base_url=None,
        apkversion="1.0.0"
    ):
        self.userid = userid or os.getenv("PROSTOCKS_USER_ID")
        self.password_plain = password_plain or os.getenv("PROSTOCKS_PASSWORD")
        self.vc = vc or os.getenv("PROSTOCKS_VENDOR_CODE")
        self.api_key = api_key or os.getenv("PROSTOCKS_API_KEY")
        self.imei = imei or os.getenv("PROSTOCKS_MAC")
        self.base_url = (base_url or os.getenv("PROSTOCKS_BASE_URL")).rstrip("/")
        self.apkversion = apkversion
        self.session_token = None
        self.session = requests.Session()
        self.headers = {
            "Content-Type": "text/plain"
        }

    def sha256(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    def login(self, factor2_otp):
        """
        Login to ProStocks API using manually entered OTP (factor2).
        """
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_raw = f"{self.userid}|{self.api_key}"
        appkey_hash = self.sha256(appkey_raw)

        print("📎 App Key Raw:", appkey_raw)
        print("🔐 Hashed App Key:", appkey_hash)

        payload = {
            "uid": self.userid,
            "pwd": pwd_hash,
            "factor2": factor2_otp,
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

    def get_quotes(self, symbol, exchange="NSE"):
        try:
            tsym = urllib.parse.quote_plus(symbol.upper())
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

    def get_ltp(self, symbol, exchange="NSE"):
        try:
            quote = self.get_quotes(symbol, exchange)
            return float(quote.get("lp", 0)) if quote else None
        except Exception as e:
            print(f"❌ Error in get_ltp for {symbol}: {e}")
            return None

    def get_candles(self, token, interval="5", exchange="NSE", days=1, limit=None):
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
                return candles[-limit:] if limit else candles
            else:
                print(f"❌ get_candles error: {data.get('emsg', 'Unknown error')}")
                return []
        except Exception as e:
            print(f"❌ Exception in get_candles for {token}: {e}")
            return []


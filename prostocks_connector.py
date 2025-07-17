
import hashlib
import requests
import json
import os
import urllib.parse  # ✅ moved to top

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
                if limit:
                    return candles[-limit:]
                return candles
            else:
                print(f"❌ get_candles error: {data.get('emsg', 'Unknown error')}")
                return []
        except Exception as e:
            print(f"❌ Exception in get_candles for {token}: {e}")
            return []


    
         def place_order(self, order_params: dict):
        """
        Places an order using ProStocks API.
        Required keys in order_params: exch, tsym, qty, prc, prctyp, prd, trantype, ret
        Optional: trgprc, dscqty, bpprc, blprc, trailprc, remarks
        """
        endpoint = f"{self.base_url}/PlaceOrder"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        # Add UID and ACTID to the payload
        jdata = order_params.copy()
        jdata["uid"] = self.userid
        jdata["actid"] = self.userid  # usually actid is same as uid

        payload = {
            "jData": json.dumps(jdata),
            "jKey": self.session_token  # This is the token returned after login
        }

        try:
            response = self.session.post(endpoint, data=payload, headers=headers)
            data = response.json()

            if data.get("stat") == "Ok":
                print("✅ Order Placed Successfully")
                return {
                    "status": "success",
                    "order_id": data["norenordno"],
                    "time": data["request_time"]
                }
            else:
                print(f"❌ Order Failed: {data.get('emsg', 'Unknown error')}")
                return {
                    "status": "error",
                    "message": data.get("emsg", "Unknown error"),
                    "time": data.get("request_time")
                }

        except Exception as e:
            print(f"❌ Exception in place_order: {e}")
            return {
                "status": "error",
                "message": f"Exception: {str(e)}"
            }



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

        

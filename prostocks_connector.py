
import os
import json
import requests
import hashlib
from dotenv import load_dotenv

load_dotenv()

class ProStocksAPI:
    def __init__(self, userid=None, password=None, factor2=None, vc=None, api_key=None, imei=None, base_url=None, apkversion="1.0.0"):
        self.userid = userid or os.getenv("PROSTOCKS_USERID")
        self.password = password or os.getenv("PROSTOCKS_PASSWORD")
        self.factor2 = factor2 or os.getenv("PROSTOCKS_FACTOR2")
        self.vc = vc or os.getenv("PROSTOCKS_VC")
        self.api_key = api_key or os.getenv("PROSTOCKS_API_KEY")
        self.imei = imei or os.getenv("PROSTOCKS_IMEI")
        self.base_url = base_url or "https://api.prostocks.com/NorenWClientTP"
        self.apkversion = apkversion
        self.session = requests.Session()
        self.session_token = None
        self.headers = {"Content-Type": "application/x-www-form-urlencoded"}

    def sha256(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    def login(self):
        try:
            url = f"{self.base_url}/QuickAuth"
            hashed_password = self.sha256(self.password)

            payload = {
                "jData": json.dumps({
                    "apkversion": self.apkversion,
                    "uid": self.userid,
                    "pwd": hashed_password,
                    "factor2": self.factor2,
                    "vc": self.vc,
                    "appkey": self.api_key,
                    "imei": self.imei
                }),
                "jKey": ""
            }

            response = self.session.post(url, data=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()

            if data.get("stat") == "Ok":
                self.session_token = data["susertoken"]
                print("✅ Login successful.")
                return True, self.session_token
            else:
                print(f"❌ Login failed: {data.get('emsg')}")
                return False, data.get("emsg")

        except Exception as e:
            print(f"❌ Exception during login: {e}")
            return False, str(e)

    def get_candles(self, exch, token, interval, from_date, to_date):
        try:
            url = f"{self.base_url}/HisData"
            params = {
                "exch": exch,
                "token": token,
                "interval": interval,
                "from": from_date,
                "to": to_date,
                "uid": self.userid,
                "stoken": self.session_token
            }

            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("stat") == "Ok":
                return data.get("data", [])
            else:
                print(f"❌ Failed to fetch candles: {data.get('emsg')}")
                return []

        except Exception as e:
            print(f"❌ Exception in get_candles: {e}")
            return []

    def place_order(self, order_params: dict):
        """
        Places an order using ProStocks API.
        Required keys in order_params: exch, tsym, qty, prc, prctyp, prd, trantype, ret
        """
        try:
            endpoint = f"{self.base_url}/PlaceOrder"
            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            jdata = order_params.copy()
            jdata["uid"] = self.userid
            jdata["actid"] = self.userid  # usually same as uid

            payload = {
                "jData": json.dumps(jdata),
                "jKey": self.session_token
            }

            response = self.session.post(endpoint, data=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            if data.get("stat") == "Ok":
                print("✅ Order Placed Successfully")
                return {
                    "status": "success",
                    "order_id": data.get("norenordno"),
                    "time": data.get("request_time")
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

# ✅ Reusable login function
def login_ps(user_id=None, password=None, factor2=None, app_key=None):
    user_id = user_id or os.getenv("PROSTOCKS_USERID")
    password = password or os.getenv("PROSTOCKS_PASSWORD")
    factor2 = factor2 or os.getenv("PROSTOCKS_FACTOR2")
    vc = os.getenv("PROSTOCKS_VC", user_id)
    imei = os.getenv("PROSTOCKS_IMEI", "MAC123456")
    app_key = app_key or os.getenv("PROSTOCKS_API_KEY")
    base_url = os.getenv("PROSTOCKS_BASE_URL", "https://api.prostocks.com/NorenWClientTP")
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

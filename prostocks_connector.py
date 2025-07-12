
 # prostocks_connector.py
import hashlib
import requests

class ProStocksAPI:
    def __init__(self, userid, password, pan_dob, vc, api_key, imei, base_url="https://api.prostocks.com"):
        self.userid = userid
        self.password = password
        self.pan_dob = pan_dob
        self.vc = vc
        self.api_key = api_key
        self.imei = imei
        self.base_url = base_url.rstrip("/")
        self.session_token = None
        self.headers = {
            "Content-Type": "application/json"
        }

    def login(self):
        url = f"{self.base_url}/NorenWClientTP/QuickAuth"
        payload = {
            "uid": self.userid,
            "pwd": self.password,
            "factor2": self.pan_dob,
            "vc": self.vc,
            "apikey": self.api_key,
            "imei": self.imei
        }

        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("stat") == "Ok":
                    self.session_token = data["susertoken"]
                    self.headers["Authorization"] = self.session_token
                    print("✅ Login Success!")
                    return True, self.session_token
                else:
                    print("❌ Login failed:", data.get("emsg"))
                    return False, data.get("emsg", "Unknown login error")
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            print("❌ Login Exception:", e)
            return False, f"RequestException: {e}"

    def get_ltp(self, symbol):
        if not self.session_token:
            return None

        url = f"{self.base_url}/NorenWClientTP/GetQuotes"
        payload = {
            "uid": self.userid,
            "exch": "NSE",
            "token": symbol
        }

        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return float(data["lp"]) if "lp" in data else None
            return None
        except:
            return None

    def place_bracket_order(self, symbol, qty, price, sl, target, side="BUY"):
        if not self.session_token:
            return False

        url = f"{self.base_url}/NorenWClientTP/PlaceOrder"
        payload = {
            "uid": self.userid,
            "actid": self.userid,
            "exch": "NSE",
            "tsym": symbol,
            "qty": qty,
            "prc": price,
            "trgprc": sl,
            "trailing_sl": 0,
            "ret": "DAY",
            "prd": "I",
            "trantype": side,
            "ordtyp": "LIMIT",
            "bpprc": target,
            "bpparms": "SL-LMT"
        }

        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=10)
            return response.status_code == 200 and response.json().get("stat") == "Ok"
        except:
            return False


# ────── Called from app.py ────────────────────────────────
def login_ps(user_id, password, factor2, app_key=None):
    if not all([user_id, password, factor2]):
        return None

    imei = os.getenv("IMEI", "abc1234")
    vc = user_id
    app_key = app_key or os.getenv("PROSTOCKS_API_KEY", "pssUATAPI12122021ASGND1234DL")

    try:
        print("📶 Login attempt started...")
        print("User ID:", user_id)

        api = ProStocksAPI(user_id, password, factor2, vc, app_key, imei)
        success, result = api.login()

        if success:
            print("✅ ps_api object created:", type(api))
            print("✅ Login Token:", result)
            return api
        else:
            print("❌ Login Failed:", result)
            return None
    except Exception as e:
        print("❌ Login Error:", e)
        return None

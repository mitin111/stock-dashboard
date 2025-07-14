
import hashlib
import requests
import os
import json

class ProStocksAPI:
    def __init__(self, userid, password_plain, factor2, vc, api_key, imei, base_url):
        self.userid = userid
        self.password_plain = password_plain
        self.factor2 = factor2
        self.vc = vc
        self.api_key = api_key
        self.imei = imei
        self.base_url = base_url.rstrip("/")
        self.session_token = None
        self.session = requests.Session()
        self.headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

    def sha256(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    def login(self):  # ✅ Not nested under sha256
        """
        Logs in to the ProStocks API using hashed credentials.
        """
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_hash = self.sha256(f"{self.userid}|{self.api_key}")

        payload = {
            "uid": self.userid,
            "pwd": pwd_hash,
            "factor2": self.factor2,
            "vc": self.vc,
            "appkey": appkey_hash,
            "imei": self.imei,
            "apkversion": "1.0.0",
            "source": "API"
        }

        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            self.headers["Content-Type"] = "text/plain"

            response = self.session.post(
                url,
                data=raw_data,
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("stat") == "Ok":
                    self.session_token = data["susertoken"]
                    self.headers["Authorization"] = self.session_token
                    return True, self.session_token
                else:
                    return False, data.get("emsg", "Unknown login error")
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"RequestException: {e}"

    def get_ltp(self, symbol):
        """
        Fetches the latest traded price (LTP) for a given symbol.
        """
        if not self.session_token:
            print("❌ Session token missing. Login required.")
            return None

        url = f"{self.base_url}/GetQuotes"
        payload = {
            "uid": self.userid,
            "exch": "NSE",
            "token": symbol
        }

        try:
            response = self.session.post(
                url,
                data={"jData": json.dumps(payload)},
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return float(data.get("lp", 0))
            else:
                print("❌ Failed to fetch LTP:", response.text)
                return None
        except Exception as e:
            print("❌ LTP fetch error:", e)
            return None

    def place_bracket_order(self, symbol, qty, price, sl, target, side="BUY"):
        """
        Places a bracket order for the given symbol.
        """
        if not self.session_token:
            print("❌ Session token missing. Login required.")
            return False

        url = f"{self.base_url}/PlaceOrder"
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
            "prd": "I",  # Intraday
            "trantype": side,
            "ordtyp": "LIMIT",
            "bpprc": target,
            "bpparms": "SL-LMT"
        }

        try:
            response = self.session.post(
                url,
                data={"jData": json.dumps(payload)},
                headers=self.headers,
                timeout=10
            )
            data = response.json()
            if response.status_code == 200 and data.get("stat") == "Ok":
                print("✅ Order placed:", data)
                return True
            else:
                print("❌ Order failed:", data)
                return False
        except Exception as e:
            print("❌ Order exception:", e)
            return False


# ──────────────────────────────────────────────────────────────
# ✅ Wrapper function for login
# ──────────────────────────────────────────────────────────────
def login_ps(user_id, password, factor2, app_key=None):
    """
    Handles user login and returns an authenticated ProStocksAPI instance.
    """
    if not all([user_id, password, factor2]):
        print("❌ Missing required login credentials.")
        return None

    imei = os.getenv("PROSTOCKS_MAC", "abc1234")
    vc = os.getenv("PROSTOCKS_VENDOR_CODE", user_id)
    app_key = app_key or os.getenv("PROSTOCKS_API_KEY", "pssUATAPI12122021ASGND1234DL")
    base_url = os.getenv("PROSTOCKS_BASE_URL", "https://starapiuat.prostocks.com/NorenWClientTP")

    try:
        print("📶 Logging in...")
        api = ProStocksAPI(user_id, password, factor2, vc, app_key, imei, base_url)
        success, result = api.login()
        if success:
            print("✅ Login successful!")
            return api
        else:
            print("❌ Login failed:", result)
            return None
    except Exception as e:
        print("❌ Login Exception:", e)
        return None


 # prostocks_connector.py
import os
import hashlib
import requests

# ────── Manual Login Class ───────────────────────────────
class ProStocksAPI:
    def __init__(self, user_id, password, factor2, vc, app_key, imei):
        self.user_id = user_id
        self.password = password
        self.factor2 = factor2  # TOTP or PAN
        self.vc = vc
        self.app_key = app_key
        self.imei = imei
        self.token = None

    def login(self):
        pwd_sha = hashlib.sha256(self.password.encode()).hexdigest()
        appkey_raw = self.user_id + "|" + self.app_key
        appkey_sha = hashlib.sha256(appkey_raw.encode()).hexdigest()

        payload = {
            "apkversion": "1.0.9",
            "uid": self.user_id,
            "pwd": pwd_sha,
            "factor2": self.factor2,
            "vc": self.user_id,  # Or self.vc if vendor code is different
            "appkey": appkey_sha,
            "imei": self.imei,
            "source": "API"
        }

        headers = {"Content-Type": "text/plain"}
        url = "https://apitest.prostocks.com/NorenWClientTP/QuickAuth"

        try:
            response = requests.post(url, json={"jData": payload}, headers=headers)
            data = response.json()
            if data.get("stat") == "Ok":
                self.token = data.get("susertoken")
                print("✅ Login Success!")
                return True, self.token
            else:
                print("❌ Login failed:", data.get("emsg"))
                return False, data.get("emsg", "Unknown error")
        except Exception as e:
            print("❌ Login Exception:", e)
            return False, str(e)

# ────── Called from app.py ────────────────────────────────
def login_ps():
    user_id = os.getenv("PROSTOCKS_USER_ID")
    password = os.getenv("PROSTOCKS_PASSWORD")
    factor2 = os.getenv("PROSTOCKS_TOTP_SECRET")  # could be PAN/DOB/TOTP
    app_key = os.getenv("PROSTOCKS_API_KEY", "pssUATAPI12122021ASGND1234DL")
    imei = os.getenv("IMEI", "abc1234")
    vc = user_id

    if not all([user_id, password, factor2]):
        return None, "Missing credentials"

    try:
        api = ProStocksAPI(user_id, password, factor2, vc, app_key, imei)
        success, result = api.login()
        if success:
            print("✅ ps_api object created:", type(api))
            return api, None
        else:
            return None, result
    except Exception as e:
        return None, str(e)

print("📦 prostocks_connector loaded")

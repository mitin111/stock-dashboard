
 # prostocks_connector.py
import hashlib
import requests
#from NorenRestApiPy.NorenApi import NorenApi   # No longer used if you bypass its login

# ────── Manual Login Class ───────────────────────────────
class ProStocksAPI:
    def __init__(self, user_id, password, factor2, vc, app_key, imei):
        # Save the credentials provided by the user
        self.user_id = user_id
        self.password = password
        self.factor2 = factor2  # Could be PAN or DOB
        self.vc = vc
        self.app_key = app_key
        self.imei = imei
        self.token = None

    def login(self):
        # Hash the password using SHA256
        pwd_sha = hashlib.sha256(self.password.encode()).hexdigest()
        # Create the appkey by combining user_id and the known API key, then hash it.
        appkey_raw = self.user_id + "|" + self.app_key
        appkey_sha = hashlib.sha256(appkey_raw.encode()).hexdigest()

        # Prepare the payload as required by the API
        payload = {
            "apkversion": "1.0.9",
            "uid": self.user_id,
            "pwd": pwd_sha,
            "factor2": self.factor2,
            "vc": self.user_id,  # Here we assume your vendor code is the user_id. Adjust if needed.
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
def login_ps(client_id, password, pan):
    try:
        # Set values for vc, app_key, and imei that are used for all logins.
        # In a manual login scenario, these can be constant or configurable in your code.
        vc = client_id  # Use client_id as vendor code if appropriate.
        app_key = "pssUATAPI12122021ASGND1234DL"  # Replace with your real API key.
        imei = "abc1234"  # This might remain a constant or be handled dynamically.

        # Create an instance of the ProStocksAPI with the manual credentials.
        api = ProStocksAPI(client_id, password, pan, vc, app_key, imei)
        success, result = api.login()

        if success:
            print("✅ ps_api object created:", type(api))
            return api
        else:
            print("❌ Login Failed:", result)
            return None
    except Exception as e:
        print("❌ Login Error:", e)
        return None

print("📦 prostocks_connector loaded")

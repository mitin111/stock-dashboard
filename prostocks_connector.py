
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

    def send_otp(self):
        """
        Trigger OTP by sending login request with empty factor2.
        ProStocks sends OTP to Email/SMS automatically.
        """
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_raw = f"{self.userid}|{self.api_key}"
        appkey_hash = self.sha256(appkey_raw)

        payload = {
            "uid": self.userid,
            "pwd": pwd_hash,
            "factor2": "",  # Empty OTP triggers OTP
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
            print("📨 OTP Trigger Response:", response.text)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"emsg": str(e)}

    def login(self, factor2_otp):
        """
        Login to ProStocks API using manually entered OTP (factor2).
        """
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_raw = f"{self.userid}|{self.api_key}"
        appkey_hash = self.sha256(appkey_raw)

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
            print("🔁 Login Response Code:", response.status_code)
            print("📨 Login Response Body:", response.text)

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

       # === Watchlist: Get List of Watchlist Names ===
    def get_watchlists(self):
        url = f"{self.base_url}/MWList"
        payload = {
            "uid": self.userid
        }
        return self._post_json(url, payload)

    # === Watchlist: Get Scrips in a Watchlist ===
    def get_watchlist(self, wlname):
        url = f"{self.base_url}/MarketWatch"
        payload = {
            "uid": self.userid,
            "wlname": wlname
        }
        return self._post_json(url, payload)

    # === Watchlist: Search Scrips by Text ===
    def search_scrip(self, search_text, exch="NSE"):
        url = f"{self.base_url}/SearchScrip"
        payload = {
            "uid": self.userid,
            "stext": search_text,
            "exch": exch
        }
        return self._post_json(url, payload)

    # === Watchlist: Add Multiple Scrips to Watchlist ===
    def add_scrips_to_watchlist(self, wlname, scrips):
        url = f"{self.base_url}/AddMultiScripsToMW"
        payload = {
            "uid": self.userid,
            "wlname": wlname,
            "scrips": scrips
        }
        return self._post_json(url, payload)

    # === Watchlist: Delete Multiple Scrips from Watchlist ===
    def delete_scrips_from_watchlist(self, wlname, scrips):
        url = f"{self.base_url}/DeleteMultiMWScrips"
        payload = {
            "uid": self.userid,
            "wlname": wlname,
            "scrips": scrips
        }
        return self._post_json(url, payload)

   # === Helper function for posting JSON with jKey ===
def _post_json(self, url, payload):
    if not self.session_token:
        return {"stat": "Not_Ok", "emsg": "Not Logged In. Session Token Missing."}

    try:
        jdata = json.dumps(payload, separators=(",", ":"))
        encoded_data = f"jData={urllib.parse.quote(jdata)}&jKey={urllib.parse.quote(self.session_token)}"

        response = self.session.post(
            url,
            data=encoded_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10
        )
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"stat": "Not_Ok", "emsg": str(e)}




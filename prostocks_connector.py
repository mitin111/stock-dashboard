
import requests
import hashlib
import json
import os
import time
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

        self.credentials = {
            "uid": self.userid,
            "pwd": self.password_plain,
            "vc": self.vc,
            "api_key": self.api_key,
            "imei": self.imei
        }

    def sha256(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    def send_otp(self):
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_raw = f"{self.userid}|{self.api_key}"
        appkey_hash = self.sha256(appkey_raw)

        payload = {
            "uid": self.userid,
            "pwd": pwd_hash,
            "factor2": "",
            "vc": self.vc,
            "appkey": appkey_hash,
            "imei": self.imei,
            "apkversion": self.apkversion,
            "source": "API"
        }

        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            response = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            print("📨 OTP Trigger Response:", response.text)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"emsg": str(e)}

    def login(self, factor2_otp):
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
            response = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            print("🔁 Login Response Code:", response.status_code)
            print("📨 Login Response Body:", response.text)

            if response.status_code == 200:
                data = response.json()
                if data.get("stat") == "Ok":
                    self.session_token = data["susertoken"]
                    self.userid = data["uid"]
                    self.headers["Authorization"] = self.session_token
                    print("✅ Login Success!")
                    return True, self.session_token
                else:
                    return False, data.get("emsg", "Unknown login error")
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"RequestException: {e}"

    # === Watchlist APIs ===

    def get_watchlists(self):
        url = f"{self.base_url}/MWList"
        payload = {"uid": self.userid}
        return self._post_json(url, payload)

    def get_watchlist_names(self):
        resp = self.get_watchlists()
        if resp.get("stat") == "Ok":
            return sorted(resp["values"], key=int)
        return []

    def get_watchlist(self, wlname):
        url = f"{self.base_url}/MarketWatch"
        payload = {"uid": self.userid, "wlname": wlname}
        return self._post_json(url, payload)

    def search_scrip(self, search_text, exch="NSE"):
        url = f"{self.base_url}/SearchScrip"
        payload = {"uid": self.userid, "stext": search_text, "exch": exch}
        return self._post_json(url, payload)

    def add_scrips_to_watchlist(self, wlname, scrips_list):
        url = f"{self.base_url}/AddMultiScripsToMW"
        scrips_str = ",".join(scrips_list)
        payload = {"uid": self.userid, "wlname": wlname, "scrips": scrips_str}
        return self._post_json(url, payload)

    def delete_scrips_from_watchlist(self, wlname, scrips_list):
        url = f"{self.base_url}/DeleteMultiMWScrips"
        scrips_str = ",".join(scrips_list)
        payload = {"uid": self.userid, "wlname": wlname, "scrips": scrips_str}
        return self._post_json(url, payload)

         # === TPSeries API ===

    # === TPSeries API ===
def get_tpseries(self, exch, token, interval="5", st=None, et=None):
    """
    Fetch TPSeries OHLC data for a symbol.
    """
    if st is None or et is None:
        et = int(time.time())
        st = et - (300 * int(interval) * 60)  # fallback to 300 candles if not passed

    url = f"{self.base_url}/TPSeries"
    
    payload = {
        "uid": self.userid,
        "exch": exch,
        "token": str(token),
        "st": st,
        "et": et,
        "intrv": interval
    }

    # ✅ Debug Logging for Payload
    print("📤 Sending TPSeries Payload:")
    print(f"  UID    : {payload['uid']}")
    print(f"  EXCH   : {payload['exch']}")
    print(f"  TOKEN  : {payload['token']}")
    print(f"  ST     : {payload['st']} → {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st))}")
    print(f"  ET     : {payload['et']} → {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(et))}")
    print(f"  INTRV  : {payload['intrv']}")

    try:
        response = self._post_json(url, payload)
        print("📨 TPSeries Response:", response)
        return response
    except Exception as e:
        print("❌ Exception in get_tpseries():", e)
        return {"stat": "Not_Ok", "emsg": str(e)}

    def fetch_tpseries_for_watchlist(self, wlname, interval="5", bars=50):
    results = []
    MAX_CALLS_PER_MIN = 20  # Avoid rate limits
    call_count = 0

    symbols = self.get_watchlist(wlname)
    if not symbols or "values" not in symbols:
        st.error("❌ No symbols found in watchlist.")
        return []

    for idx, sym in enumerate(symbols["values"]):
        exch = sym.get("exch", "").strip()
        token = sym.get("token", "").strip()
        symbol = sym.get("tsym", "").strip()

        # 🛡️ Defensive Checks
        if not token or not str(token).isdigit():
            print(f"⚠️ Skipping {symbol}: Invalid or missing token ({token})")
            continue
        if exch != "NSE":
            print(f"⚠️ Skipping {symbol}: Unsupported exchange ({exch})")
            continue

        # ⏳ Time Calculations
        try:
            now = int(time.time())
            interval_sec = int(interval) * 60
            st_time = now - (bars * interval_sec)
            et_time = now
        except Exception as e:
            print(f"⚠️ Time conversion error for {symbol}: {e}")
            continue

        print(f"\n📦 {idx+1}. {symbol} → {exch}|{token}")
        print("📤 TPSeries Payload Preview:")
        print(f"  UID    : {self.userid}")
        print(f"  EXCH   : {exch}")
        print(f"  TOKEN  : {token}")
        print(f"  ST     : {st_time}")
        print(f"  ET     : {et_time}")
        print(f"  INTRV  : {interval}")

        try:
            response = self.get_tpseries(
                exch=exch,
                token=token,
                interval=interval,
                st=st_time,
                et=et_time
            )
            if isinstance(response, list):
                print(f"✅ {symbol}: {len(response)} candles fetched.")
                results.append({
                    "symbol": symbol,
                    "data": response
                })
            else:
                print(f"⚠️ {symbol}: Error Occurred : {response.get('stat')} \"{response.get('emsg')}\"")
        except Exception as e:
            print(f"❌ {symbol}: Exception: {e}")

        call_count += 1
        if call_count >= MAX_CALLS_PER_MIN:
            print("⚠️ TPSeries limit reached. Skipping remaining.")
            break

    return results

    # === Internal Helper ===

    def _post_json(self, url, payload):
        if not self.session_token:
            return {"stat": "Not_Ok", "emsg": "Not Logged In. Session Token Missing."}
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}&jKey={self.session_token}"
            print("✅ POST URL:", url)
            print("📦 Sent Payload:", jdata)

            response = self.session.post(
                url,
                data=raw_data,
                headers={"Content-Type": "text/plain"},
                timeout=10
            )
            print("📨 Response:", response.text)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"stat": "Not_Ok", "emsg": str(e)}




 # prostocks_connector.py
import os
import hashlib
import requests

# ────── Manual Login Class ───────────────────────────────
class ProStocksAPI:
    def login_ps():
    user_id = os.getenv("PROSTOCKS_USER_ID")
    password = os.getenv("PROSTOCKS_PASSWORD")
    factor2 = os.getenv("PROSTOCKS_TOTP_SECRET")
    app_key = os.getenv("PROSTOCKS_API_KEY", "pssUATAPI12122021ASGND1234DL")
    imei = os.getenv("IMEI", "abc1234")
    vc = user_id

    print("🔐 DEBUG: Loaded credentials:")
    print(f"user_id={user_id}, password={'****' if password else None}, factor2={'****' if factor2 else None}, app_key={'****' if app_key else None}")

    if not all([user_id, password, factor2]):
        print("❌ Missing one or more required credentials.")
        return None, "Missing credentials"

    try:
        api = ProStocksAPI(user_id, password, factor2, vc, app_key, imei)
        success, result = api.login()
        if success:
            print("✅ ps_api object created:", type(api))
            return api, None
        else:
            print("❌ Login Failed:", result)
            return None, result
    except Exception as e:
        print("❌ Login Error:", e)
        return None, str(e)

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

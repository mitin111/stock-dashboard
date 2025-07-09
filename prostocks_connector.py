# prostocks_connector.py
from prostocks_login_app import ProStocksAPI  # ✅ Make sure this file exists

def login_ps(client_id, password, pan):
    try:
        # 🛠️ Replace these with your real credentials
        vc = "FA12345"  # Vendor Code from ProStocks
        app_key = "your_api_key_here"  # API Secret Key
        imei = "abc123xyz"  # Device ID / IMEI

        api = ProStocksAPI(
            user_id=client_id,
            password=password,
            factor2=pan,
            vc=vc,
            app_key=app_key,
            imei=imei
        )

        success, result = api.login()

        if success:
            print("✅ Login successful.")
            return api
        else:
            print("❌ Login failed:", result)
            return None
    except Exception as e:
        print("❌ Login error:", str(e))
        return None

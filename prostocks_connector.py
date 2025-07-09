from prostocks_login_app import ProStocksAPI  # Make sure the path/module is correct

def login_ps(client_id, password, pan):
    try:
        # 🔑 Replace the credentials below with your actual ProStocks developer credentials
        vc = "FA12345"               # Vendor Code from ProStocks (e.g., "FA12345")
        app_key = "your_api_key_here"  # API secret key from developer account
        imei = "abc123xyz"           # IMEI/device ID (can be a fixed string, like "mitin-device-01")

        # Initialize the ProStocks API session object
        api = ProStocksAPI(
            user_id=client_id,
            password=password,
            factor2=pan,
            vc=vc,
            app_key=app_key,
            imei=imei
        )

        # Perform login
        success, result = api.login()

        if success:
            print("✅ ps_api object created:", type(api))
            return api  # Return the API object to use later for trading
        else:
            print("❌ Login Failed:", result)
            return None

    except Exception as e:
        print("❌ Login Error:", e)
        return None

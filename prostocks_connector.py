# prostocks_connector.py

from NorenRestApiPy.NorenApi import NorenApi

# 🔐 Full Login Class (merged here)
class ProStocksAPI(NorenApi):
    def __init__(self, user_id, password, factor2, vc, app_key, imei):
        super().__init__(
            host="https://www.prostocks.com/tradeapi",
            websocket="wss://www.prostocks.com/NorenWS/"
        )
        self.user_id = user_id
        self.password = password
        self.factor2 = factor2
        self.vc = vc
        self.app_key = app_key
        self.imei = imei
        self.token = None

    def login(self):
        try:
            response = super().login(
                userid=self.user_id,
                password=self.password,
                twoFA=self.factor2,
                vendor_code=self.vc,
                api_secret=self.app_key,
                imei=self.imei,
                app_key=self.app_key
            )
            if response.get('stat') == 'Ok':
                self.token = response['susertoken']
                print("✅ Login Success!")
                return True, self.token
            else:
                print("❌ Login failed:", response)
                return False, response.get("emsg", "Unknown error")
        except Exception as e:
            print("❌ Login Exception:", e)
            return False, str(e)

# 🔁 Called from app.py
def login_ps(client_id, password, pan):
    try:
        # ✅ Replace with your actual credentials from ProStocks developer panel
        vc = "FA12345"
        app_key = "your_api_key_here"
        imei = "abc123xyz"

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

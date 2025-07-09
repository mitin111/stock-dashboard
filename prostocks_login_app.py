# prostocks_login_app.py
from NorenRestApiPy.NorenApi import NorenApi

class ProStocksAPI(NorenApi):
    def __init__(self, user_id, password, factor2, vc, app_key, imei):
        host = "https://www.prostocks.com/tradeapi"
        websocket = "wss://www.prostocks.com/NorenWS/"
        super().__init__(host=host, websocket=websocket)

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
                print("✅ Login successful.")
                self.token = response['susertoken']
                return True, self.token
            else:
                print("❌ Login failed:", response)
                return False, response.get("emsg", "Unknown error")
        except Exception as e:
            print("❌ Login error:", e)
            return False, str(e)

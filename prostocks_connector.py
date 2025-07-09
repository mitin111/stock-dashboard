from NorenRestApiPy.NorenApi import NorenApi
from dotenv import load_dotenv
import os
import requests

# Load .env values
load_dotenv()

class ProStocksAPI(NorenApi):
    def __init__(self):
        super().__init__()
        self.user_id = os.getenv("PROSTOCKS_UID")
        self.password = os.getenv("PROSTOCKS_PASSWORD")
        self.factor2 = "123456"
        self.vc = os.getenv("PROSTOCKS_VC")
        self.app_key = os.getenv("PROSTOCKS_API_SECRET")
        self.imei = os.getenv("PROSTOCKS_IMEI")
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
                app_key=os.getenv("PROSTOCKS_APP_KEY")
            )
            if response['stat'] == 'Ok':
                print("✅ Login successful.")
                self.token = response['susertoken']
            else:
                print("❌ Login failed:", response)
        except Exception as e:
            print("Login Error:", e)

    def get_ltp(self, symbol):
        try:
            data = self.get_quotes(exchange='NSE', token=symbol)
            return float(data['lp'])  # Last traded price
        except Exception as e:
            print(f"Error fetching LTP for {symbol}: {e}")
            return None

    def place_bracket_order(self, symbol, qty, price, sl, target, side="BUY"):
        try:
            order_type = "B" if side.upper() == "BUY" else "S"
            response = self.place_order(
                buy_or_sell=order_type,
                product_type="I",
                exchange="NSE",
                tradingsymbol=symbol,
                quantity=qty,
                discloseqty=0,
                price_type="LIMIT",
                price=price,
                trigger_price=0,
                retention="DAY",
                amo="NO",
                remarks="Bracket Order",
                booklossprice=sl,
                bookprofitprice=target,
                trailprice=0
            )
            return response
        except Exception as e:
            print(f"Order error: {e}")
            return None

    def get_candles(self, symbol, interval="5minute", days=1):
        try:
            url = f"{self.base_url}/GetCandleData"
            params = {
                "uid": self.user_id,
                "token": self.token,
                "exch": "NSE",
                "symbol": symbol,
                "interval": interval,
                "days": str(days)
            }

            response = requests.get(url, params=params)
            data = response.json()

            if data.get("status") != "Ok" or not data.get("data"):
                print(f"⚠️ Candle fetch failed: {data}")
                return []

            candles = []
            for item in data["data"]:
                candles.append({
                    "time": item["time"],
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                    "volume": float(item["volume"])
                })

            return candles

        except Exception as e:
            print(f"❌ Error in get_candles(): {e}")
            return []


# prostocks_login_app.py
import streamlit as st
from prostocks_connector import ProStocksAPI

st.set_page_config(page_title="🔐 ProStocks Login", layout="centered")

st.title("🔐 ProStocks API Login")

with st.form("login_form"):
    uid = st.text_input("User ID", value="", max_chars=30)
    pwd = st.text_input("Password", type="password")
    factor2 = st.text_input("PAN / DOB (DD-MM-YYYY)")
    vc = st.text_input("Vendor Code")
    api_key = st.text_input("API Key", type="password")
    imei = st.text_input("IMEI (MAC or Unique ID)", value="MAC123456")

    submitted = st.form_submit_button("Login")

if submitted:
    if all([uid, pwd, factor2, vc, api_key, imei]):
        # Instantiate with user inputs
        api = ProStocksAPI(uid, pwd, factor2, vc, api_key, imei)
        success, result = api.login()

        if success:
            st.success("✅ Login successful.")
            st.code(result, language="bash")  # Display token
        else:
            st.error(f"❌ Login failed: {result}")
    else:
        st.warning("⚠️ Please fill all fields to proceed.")

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



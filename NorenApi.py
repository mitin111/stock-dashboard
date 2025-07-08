
class NorenApi:
    def __init__(self):
        pass

    def login(self):
        return "Logged in successfully"

    def get_ltp(self, symbol):
        return 100.5  # Dummy LTP

    def get_candles(self, symbol, interval="5minute", days=1):
        return [{"high": 105, "low": 95}] * 20  # Dummy candle data

    def place_bracket_order(self, symbol, qty, price, sl, target, side):
        return {"status": "success", "order_id": "ABC123"}  # Dummy order response

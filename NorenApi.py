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
class NorenApiPy(NorenApi):
    def __init__(self):
        super().__init__(host='http://test.kambala.co.in:6008/NorenWClient/',
                         websocket='ws://test.kambala.co.in:9657/NorenWS/')
        global api
        api = self

    def get_ltp(self, symbol, exchange="NSE"):
        try:
            quote = self.get_quotes(exchange=exchange, tradingsymbol=symbol)
            return float(quote['lp'])  # 'lp' = Last traded price
        except Exception as e:
            print(f"Error in get_ltp for {symbol}: {e}")
            return None

    # You may already have other methods like placeOrder(), etc.

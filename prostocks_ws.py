import json
import time
import queue
import threading
import websocket


class ProStocksWS:
    """
    Wrapper class for ProStocks WebSocket
    - Readability के लिए नाम ProStocksWS रखा गया है
    - अंदर actual implementation ProStocksWebSocket जैसा ही है
    """

    def __init__(self, userid, session_token, tick_file="ticks.log"):
        self.userid = userid
        self.session_token = session_token
        self.tick_file = tick_file
        self.ws = None
        self.is_ws_connected = False
        self._sub_tokens = []
        self._on_tick = None
        self.tick_queue = queue.Queue()
        self.candles = {}

    # -------------------- WebSocket Events --------------------
    def _ws_on_message(self, ws, message):
        try:
            tick = json.loads(message)

            # ✅ Login ACK
            if isinstance(tick, dict) and tick.get("t") == "ck":
                if tick.get("s") in ["OK", "Ok"]:
                    print("✅ WebSocket login OK")
                    if self._sub_tokens:
                        self.subscribe_tokens(self._sub_tokens)
                else:
                    print("❌ WebSocket login failed:", tick)
                return

            # ✅ Tick data
            print("📩 Tick received:", tick)

            # File log
            with open(self.tick_file, "a") as f:
                f.write(json.dumps(tick) + "\n")

            # Queue
            self.tick_queue.put(tick)

            # Callback
            if self._on_tick:
                try:
                    self._on_tick(tick)
                except Exception as e:
                    print("❌ on_tick callback error:", e)

            # Candle builder
            try:
                self.build_live_candles_from_tick(tick)
            except Exception as e:
                print("⚠️ candle build error:", e)

        except Exception as e:
            print("⚠️ _ws_on_message parse error:", e)

    def _ws_on_open(self, ws):
        self.is_ws_connected = True
        print("✅ WebSocket connected")

        login_pkt = {
            "t": "c",
            "uid": self.userid,
            "actid": self.userid,
            "susertoken": self.session_token,
            "source": "API",
        }
        ws.send(json.dumps(login_pkt))
        print("🔑 WS login sent")

    def _ws_on_close(self, ws, code, msg):
        self.is_ws_connected = False
        print("❌ WebSocket closed:", code, msg)

    def _ws_on_error(self, ws, error):
        print("⚠️ WebSocket error:", error)

    # -------------------- Actions --------------------
    def subscribe_tokens(self, tokens):
        if not self.ws:
            print("⚠️ subscribe_tokens: WS not connected yet")
            return
        if not tokens:
            print("⚠️ subscribe_tokens: Empty token list")
            return

        uniq = []
        seen = set()
        for k in tokens:
            if k and k not in seen:
                uniq.append(k)
                seen.add(k)

        sub_req = {"t": "t", "k": "#".join(uniq)}
        try:
            self.ws.send(json.dumps(sub_req))
            print(f"📡 Subscribed: {uniq}")
        except Exception as e:
            print("❌ subscribe_tokens error:", e)

    def stop_ticks(self):
        try:
            if self.ws:
                self.ws.close()
                self.is_ws_connected = False
                print("🛑 WebSocket stop requested")
        except Exception as e:
            print("❌ stop_ticks error:", e)

    def build_live_candles_from_tick(self, tick, intervals=[1, 3, 5, 15, 30, 60]):
        try:
            ts = int(tick.get("ft", 0))   # epoch seconds
            price = float(tick.get("lp", 0) or 0)
            volume = int(tick.get("v", 0) or 0)

            if not price:
                return

            exch = tick.get("e")
            token = tick.get("tk")

            for m in intervals:
                bucket = ts - (ts % (m * 60))
                key = f"{exch}|{token}|{m}"

                if key not in self.candles:
                    self.candles[key] = {}

                if bucket not in self.candles[key]:
                    self.candles[key][bucket] = {
                        "ts": bucket,
                        "o": price,
                        "h": price,
                        "l": price,
                        "c": price,
                        "v": volume,
                    }
                else:
                    candle = self.candles[key][bucket]
                    candle["h"] = max(candle["h"], price)
                    candle["l"] = min(candle["l"], price)
                    candle["c"] = price
                    candle["v"] += volume

        except Exception as e:
            print(f"⚠️ build_live_candles_from_tick error: {e}, tick={tick}")

    def connect_websocket(self, symbols, on_tick=None, tick_file="ticks.log"):
        try:
            self._on_tick = on_tick
            self.start_ticks(symbols, tick_file=tick_file)

            for _ in range(50):
                if self.is_ws_connected:
                    print("✅ WebSocket connected")
                    return True
                time.sleep(0.1)

            print("❌ WebSocket connect timeout")
            return False

        except Exception as e:
            print("❌ connect_websocket error:", e)
            return False

    def start_ticks(self, symbols, tick_file="ticks.log"):
        self.tick_file = tick_file
        self.tick_queue = queue.Queue()
        self._sub_tokens = symbols
        self.is_ws_connected = False

        def run_ws():
            try:
                ws_url = "wss://starapi.prostocks.com/NorenWSTP/"
                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_message=self._ws_on_message,
                    on_open=self._ws_on_open,
                    on_error=self._ws_on_error,
                    on_close=self._ws_on_close,
                )
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                print("❌ start_ticks websocket error:", e)

        t = threading.Thread(target=run_ws, daemon=True)
        t.start()

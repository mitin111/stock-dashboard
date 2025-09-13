# prostocks_ws.py
import json
import time
import threading
import queue
import websocket


class ProStocksWebSocket:
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

    # ---------------- WS Events ----------------
   def _ws_on_message(self, ws, message):
        try:
            tick = json.loads(message)
            # Optional: login-ack handle (ProStocks me 'ck' aata hai)
            if isinstance(tick, dict) and tick.get("t") == "ck":
                if tick.get("s") in ["OK", "Ok"]:   # <-- FIXED ✅
                    print("✅ WebSocket login OK")
                    # re-subscribe after login ack if tokens present
                    if hasattr(self, "_sub_tokens") and self._sub_tokens:
                        self.subscribe_tokens(self._sub_tokens)
                else:
                    print("❌ WebSocket login failed:", tick)
                return

            # 📩 Normal tick data
            print("📩 Tick received:", tick)

            # ✅ File me append karo
            with open(self.tick_file, "a") as f:
                f.write(json.dumps(tick) + "\n")
                
            # ✅ Queue me bhejo (safe for Streamlit consumer thread)
            self.tick_queue.put(tick)
                
            # Callback trigger
            if hasattr(self, "_on_tick") and self._on_tick:
                try:
                    self._on_tick(tick)
                except Exception as e:
                    print("❌ on_tick callback error:", e)

            # ✅ Live candle builder update
            try:
                self.build_live_candles_from_tick(tick)
            except Exception as e:
                print("⚠️ candle build error:", e)
                
        except Exception as e:
            print("⚠️ _ws_on_message parse error:", e)

    def _ws_on_open(self, ws):
        self.is_ws_connected = True
        print("✅ WebSocket connected")

        # Login packet (UID/JKEY dynamically from successful REST login)
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

    def subscribe_tokens(self, tokens):
        """
        tokens: list[str] in 'EXCH|TOKEN' format.
        ProStocks WS supports multi-subscribe with '#' separator.
        """
        if not self.ws:
            print("⚠️ subscribe_tokens: WS not connected yet")
            return
        if not tokens:
            print("⚠️ subscribe_tokens: Empty token list")
            return

        # unique + keep order
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
        """
        Stop and close the active WebSocket connection.
        """
        try:
            if hasattr(self, "ws") and self.ws:
                self.ws.close()
                self.is_ws_connected = False
                print("🛑 WebSocket stop requested")
        except Exception as e:
            print("❌ stop_ticks error:", e)

    def build_live_candles_from_tick(self, tick, intervals=[1, 3, 5, 15, 30, 60]):
        """
        Build/update OHLCV candles from live ticks.
        - tick: dict from websocket {e, tk, lp, v, ft}
        - intervals: list of minute durations [1,3,5,15,30,60]
        """
        try:
            ts = int(tick.get("ft", 0))   # epoch seconds
            price = float(tick.get("lp", 0) or 0)
            volume = int(tick.get("v", 0) or 0)

            if not price:
                return  # skip ticks without price

            exch = tick.get("e")
            token = tick.get("tk")

            for m in intervals:
                # Candle start bucket timestamp
                bucket = ts - (ts % (m * 60))
                key = f"{exch}|{token}|{m}"

                # Init storage if not exists
                if not hasattr(self, "candles"):
                    self.candles = {}
                if key not in self.candles:
                    self.candles[key] = {}

                # --- Create or update candle ---
                if bucket not in self.candles[key]:
                    # New candle
                    self.candles[key][bucket] = {
                        "ts": bucket,
                        "o": price,
                        "h": price,
                        "l": price,
                        "c": price,
                        "v": volume,
                    }
                else:
                    # Update existing candle
                    candle = self.candles[key][bucket]
                    candle["h"] = max(candle["h"], price)
                    candle["l"] = min(candle["l"], price)
                    candle["c"] = price
                    candle["v"] += volume

        except Exception as e:
            print(f"⚠️ build_live_candles_from_tick error: {e}, tick={tick}")

    def connect_websocket(self, symbols, on_tick=None, tick_file="ticks.log"):
        """
        Connect to WebSocket and subscribe to given symbols.
        - symbols: list of tokens like ['NSE|22', 'NSE|2885']
        - on_tick: callback function to handle ticks
        - tick_file: optional log file for raw ticks
        """
        try:
            self._on_tick = on_tick
            self.start_ticks(symbols, tick_file=tick_file)

            # Wait until WS connected (max 5 sec)
            for _ in range(50):
                if getattr(self, "is_ws_connected", False):
                    print("✅ WebSocket connected")
                    return True
                time.sleep(0.1)

            print("❌ WebSocket connect timeout")
            return False

        except Exception as e:
            print("❌ connect_websocket error:", e)
            return False

    def start_ticks(self, symbols, tick_file="ticks.log"):
        """
        Start WebSocket connection and subscribe to symbols.
        """
        import websocket
        import threading

        self.tick_file = tick_file
        self.tick_queue = queue.Queue()
        self._sub_tokens = symbols  # store tokens for re-subscribe after login
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

        # Run WebSocket in background
        t = threading.Thread(target=run_ws, daemon=True)
        t.start()

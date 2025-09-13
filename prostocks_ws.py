# prostocks_ws.py
import json
import time
import threading
import websocket
import queue


class ProStocksWS:
    def __init__(self, userid, session_token, tick_file="ticks.log"):
        self.userid = userid
        self.session_token = session_token
        self.ws = None
        self.is_ws_connected = False
        self.tick_file = tick_file
        self.tick_queue = queue.Queue()
        self._sub_tokens = []
        self._on_tick = None
        self.candles = {}

    def _ws_on_message(self, ws, message):
        try:
            tick = json.loads(message)
            if isinstance(tick, dict) and tick.get("t") == "ck":
                if tick.get("s") in ["OK", "Ok"]:
                    print("✅ WebSocket login OK")
                    if self._sub_tokens:
                        self.subscribe_tokens(self._sub_tokens)
                else:
                    print("❌ WebSocket login failed:", tick)
                return

            with open(self.tick_file, "a") as f:
                f.write(json.dumps(tick) + "\n")
            self.tick_queue.put(tick)
            if self._on_tick:
                self._on_tick(tick)
            self.build_live_candles_from_tick(tick)
        except Exception as e:
            print("⚠️ _ws_on_message error:", e)

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

    def subscribe_tokens(self, tokens):
        if not self.ws or not tokens:
            return
        uniq = list(dict.fromkeys(tokens))
        sub_req = {"t": "t", "k": "#".join(uniq)}
        self.ws.send(json.dumps(sub_req))
        print(f"📡 Subscribed: {uniq}")

    def stop_ticks(self):
        if self.ws:
            self.ws.close()
            self.is_ws_connected = False
            print("🛑 WebSocket stopped")

    def build_live_candles_from_tick(self, tick, intervals=[1, 3, 5, 15, 30, 60]):
        try:
            ts = int(tick.get("ft", 0))
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
                    self.candles[key][bucket] = {"ts": bucket, "o": price, "h": price, "l": price, "c": price, "v": volume}
                else:
                    c = self.candles[key][bucket]
                    c["h"] = max(c["h"], price)
                    c["l"] = min(c["l"], price)
                    c["c"] = price
                    c["v"] += volume
        except Exception as e:
            print("⚠️ build_live_candles_from_tick error:", e)

    def connect_websocket(self, symbols, on_tick=None):
        self._on_tick = on_tick
        self._sub_tokens = symbols

        def run_ws():
            self.ws = websocket.WebSocketApp(
                "wss://starapi.prostocks.com/NorenWSTP/",
                on_message=self._ws_on_message,
                on_open=self._ws_on_open,
                on_error=self._ws_on_error,
                on_close=self._ws_on_close,
            )
            self.ws.run_forever(ping_interval=20, ping_timeout=10)

        t = threading.Thread(target=run_ws, daemon=True)
        t.start()
        for _ in range(50):
            if self.is_ws_connected:
                return True
            time.sleep(0.1)
        return False

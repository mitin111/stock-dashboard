
# prostocks_connector.py
import os
import json
import time
import threading
import csv
from datetime import datetime
from typing import List, Optional, Dict, Any
import websocket
import requests  # kept for auth / optional restful helpers
from pathlib import Path

# -- Configuration defaults --
DEFAULT_WS_URL = "wss://starapi.prostocks.com/NorenWSTP/"
TICKS_DIR = Path("./ticks")
TICKS_DIR.mkdir(parents=True, exist_ok=True)


class ProStocksAPI:
    """
    ProStocksAPI - focused on live tick subscription + tick persistence (no TPSeries).
    Features:
      - start() / stop() websocket
      - add_subscription("NSE|11872")
      - remove_subscription("NSE|11872")
      - on_tick stores tick in-memory (self.tick_data[token_id]) and appends to CSV ./ticks/ticks_<token_id>.csv
      - load_historical_ticks(token_full) reads CSV into list[dict]
      - get_historical_ticks(token_full, start, end) filters loaded CSV records between timestamps
      - get_recent_ticks(token_full, n) returns last n ticks from in-memory buffer (or from CSV fallback)
    """

    def __init__(self, userid: Optional[str] = None, password_plain: Optional[str] = None,
                 vc: Optional[str] = None, api_key: Optional[str] = None, imei: Optional[str] = None,
                 base_url: Optional[str] = None, ws_url: str = DEFAULT_WS_URL, csv_dir: Path = TICKS_DIR):
        # Auth fields (optional)
        self.userid = userid
        self.password_plain = password_plain
        self.vc = vc
        self.api_key = api_key
        self.imei = imei
        self.base_url = (base_url or "https://starapi.prostocks.com/NorenWClientTP").rstrip("/")

        # WebSocket / subscription state
        self.ws_url = ws_url
        self.ws_app: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.ws_connected = False
        self._stop_event = threading.Event()

        # tokens are strings like "NSE|11872"
        self.subscribed_tokens: List[str] = []  # current target subscriptions
        self._subscriptions_lock = threading.Lock()

        # tick storage: { token_id: [ {"ts": datetime, "price": float, "volume": int, "raw": dict, "token_full": str} ] }
        self.tick_data: Dict[str, List[Dict[str, Any]]] = {}
        self._tick_lock = threading.Lock()
        self.csv_dir = csv_dir
        self.csv_dir.mkdir(parents=True, exist_ok=True)

        # config: how many ticks to keep in memory per token (bounded)
        self.max_in_memory_ticks = 2000

        # ping interval (seconds)
        self.ping_interval = 15

        # a small exponential backoff for reconnects
        self._reconnect_backoff = 1.0

    # ----------------- Utility helpers -----------------
    @staticmethod
    def _normalize_token(token_full: str):
        """Return (exch, token_id, token_key) given token like 'NSE|11872' or '11872'"""
        parts = token_full.split("|")
        if len(parts) == 2:
            exch, token_id = parts
        else:
            exch, token_id = "NSE", parts[0]
        token_key = token_id  # canonical key to store ticks by
        return exch, token_id, token_key

    def _csv_path_for_token(self, token_id: str) -> Path:
        return self.csv_dir / f"ticks_{token_id}.csv"

    def _append_tick_to_csv(self, token_full: str, token_id: str, ts: datetime, price: float, volume: int, raw: dict):
        """Append a single tick row to CSV (create header if missing)."""
        csv_path = self._csv_path_for_token(token_id)
        row = {
            "ts_iso": ts.isoformat(),
            "token_full": token_full,
            "token_id": token_id,
            "price": price,
            "volume": volume,
            "raw_json": json.dumps(raw, separators=(",", ":"), ensure_ascii=False)
        }
        write_header = not csv_path.exists()
        with open(csv_path, "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    # ----------------- Tick handling -----------------
    def on_tick(self, raw_data: dict):
        """
        Called when a tick message is received from websocket.
        Expected shape of raw_data varies; common keys:
           - 'tk' (token like 'NSE|11872')
           - 'lp' (last price)
           - 'v'  (volume) maybe cumulative or tick volume
        """
        token_full = raw_data.get("tk") or raw_data.get("token") or ""
        if not token_full:
            # not a tick
            return

        exch, token_id, token_key = self._normalize_token(token_full)

        # parse price & volume robustly
        try:
            price = float(raw_data.get("lp", raw_data.get("tradeprice", 0) or 0.0))
        except Exception:
            price = 0.0
        try:
            volume = int(float(raw_data.get("v", raw_data.get("volume", 0) or 0)))
        except Exception:
            volume = 0

        ts = datetime.utcnow()  # use UTC consistently in storage
        tick_row = {"ts": ts, "price": price, "volume": volume, "raw": raw_data, "token_full": token_full}

        # store in-memory
        with self._tick_lock:
            lst = self.tick_data.setdefault(token_key, [])
            lst.append(tick_row)
            # bound the in-memory buffer
            if len(lst) > self.max_in_memory_ticks:
                # drop oldest entries
                del lst[0 : len(lst) - self.max_in_memory_ticks]

        # persist to CSV immediately
        try:
            self._append_tick_to_csv(token_full, token_key, ts, price, volume, raw_data)
        except Exception as e:
            # Do not raise — just log
            print(f"⚠️ Failed appending tick to CSV for {token_key}: {e}")

    # ----------------- Historical loader & getters -----------------
    def load_historical_ticks(self, token_full: str, max_rows: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Load historical ticks from CSV for token_full. Returns list of dicts with keys:
          ts (datetime), price (float), volume (int), raw (dict), token_full
        """
        _, token_id, token_key = self._normalize_token(token_full)
        csv_path = self._csv_path_for_token(token_key)
        if not csv_path.exists():
            return []

        rows = []
        try:
            with open(csv_path, "r", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for r in reader:
                    try:
                        ts = datetime.fromisoformat(r["ts_iso"])
                    except Exception:
                        # fallback: try parsing common formats
                        try:
                            ts = datetime.strptime(r["ts_iso"], "%Y-%m-%dT%H:%M:%S.%f")
                        except Exception:
                            continue
                    price = float(r.get("price", 0) or 0)
                    volume = int(float(r.get("volume", 0) or 0))
                    raw = {}
                    try:
                        raw = json.loads(r.get("raw_json") or "{}")
                    except Exception:
                        raw = {}
                    rows.append({"ts": ts, "price": price, "volume": volume, "raw": raw, "token_full": r.get("token_full")})
            # optionally limit to last max_rows
            if max_rows:
                rows = rows[-max_rows:]
            return rows
        except Exception as e:
            print(f"❌ Error loading historical ticks for {token_key}: {e}")
            return []

    def get_historical_ticks(self, token_full: str, start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Load ticks from CSV and filter between start and end datetimes (UTC).
        If start or end is None, the range is unbounded on that side.
        """
        rows = self.load_historical_ticks(token_full)
        if not rows:
            return []

        if start:
            rows = [r for r in rows if r["ts"] >= start]
        if end:
            rows = [r for r in rows if r["ts"] <= end]
        return rows

    def get_recent_ticks(self, token_full: str, n: int = 100) -> List[Dict[str, Any]]:
        """Return last n ticks from in-memory buffer; falls back to CSV when in-memory is empty."""
        _, token_id, token_key = self._normalize_token(token_full)
        with self._tick_lock:
            buf = list(self.tick_data.get(token_key, []))
        if buf:
            return buf[-n:]
        # fallback
        return self.load_historical_ticks(token_full, max_rows=n)

    # ----------------- WebSocket lifecycle -----------------
    def _on_ws_message(self, ws, message):
        # called from websocket thread
        try:
            data = json.loads(message)
        except Exception:
            # not JSON - ignore
            return

        # The ProStocks WS sends various messages. Ticks usually have t == "tk"
        # but servers differ; handle generically.
        if data.get("t") == "tk" or data.get("type") == "tick" or "lp" in data:
            # tick-like message
            self.on_tick(data)
        else:
            # other server messages (login ack / subscription ack / heartbeat)
            # print/debug small events
            # print("WS MSG:", data)
            if data.get("s") == "OK":
                # subscription ack
                print(f"WS subscription ack: {data}")
            # else ignore

    def _on_ws_open(self, ws):
        print("🔗 WebSocket opened")
        self.ws_connected = True
        self._reconnect_backoff = 1.0  # reset backoff after successful connect

        # Send any required handshake if needed (some servers expect a login or c message).
        # If your server requires it, uncomment and adapt:
        # ws.send(json.dumps({"t":"c","uid": self.userid, "pwd": self.password_plain, "source":"API"}))
        # Small delay to let server accept our login before subscribing
        time.sleep(0.2)

        # subscribe to existing tokens
        with self._subscriptions_lock:
            for token in self.subscribed_tokens:
                try:
                    exch, token_id, _ = self._normalize_token(token)
                    sub_msg = {"t": "t", "k": f"{exch}|{token_id}"}
                    ws.send(json.dumps(sub_msg))
                    print(f"✅ Sent subscription: {sub_msg}")
                except Exception as e:
                    print("❌ Failed send subscription:", e)

        # start ping thread for this ws (daemon)
        def ping_loop():
            while self.ws_connected and not self._stop_event.is_set():
                try:
                    ws.send(json.dumps({"t": "ping"}))
                except Exception:
                    break
                time.sleep(self.ping_interval)

        threading.Thread(target=ping_loop, daemon=True).start()

    def _on_ws_close(self, ws, close_status_code, close_msg):
        print(f"🔌 WebSocket closed: {close_status_code} - {close_msg}")
        self.ws_connected = False
        # attempt reconnect in background
        if not self._stop_event.is_set():
            threading.Thread(target=self._reconnect_loop, daemon=True).start()

    def _on_ws_error(self, ws, error):
        print("❌ WebSocket error:", error)

    def _run_ws(self):
        # create WebSocketApp and run forever (blocking)
        self.ws_app = websocket.WebSocketApp(
            self.ws_url,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
        )
        # run_forever will block the thread until connection closes
        try:
            self.ws_app.run_forever(ping_interval=self.ping_interval, ping_timeout=10)
        except Exception as e:
            print("❌ run_forever ended with exception:", e)
        finally:
            self.ws_connected = False

    def start(self, background: bool = True):
        """
        Start websocket connection. If background=True (default) this spawns a daemon thread.
        """
        self._stop_event.clear()
        # if thread already running, do nothing
        if self.ws_thread and self.ws_thread.is_alive():
            return

        self.ws_thread = threading.Thread(target=self._run_ws, daemon=True)
        self.ws_thread.start()
        # allow quick initial backoff reset
        self._reconnect_backoff = 1.0

    def stop(self):
        """Stop the websocket and prevent reconnects."""
        self._stop_event.set()
        try:
            if self.ws_app:
                self.ws_app.close()
        except Exception:
            pass
        self.ws_connected = False

    def _reconnect_loop(self):
        """Backoff reconnect loop; creates a new run_forever thread if still not stopped."""
        # prevent multiple concurrent reconnect threads
        if self._stop_event.is_set():
            return
        wait = self._reconnect_backoff
        print(f"🔁 Reconnect in {wait:.1f}s...")
        time.sleep(wait)
        # exponential backoff up to 60s
        self._reconnect_backoff = min(self._reconnect_backoff * 2.0, 60.0)
        if self._stop_event.is_set():
            return
        # spawn a new ws run thread
        try:
            self.start(background=True)
        except Exception as e:
            print("❌ Reconnect start failed:", e)

    # ----------------- Subscription management -----------------
    def add_subscription(self, token_full: str):
        """Register token for subscription and subscribe immediately if connected."""
        with self._subscriptions_lock:
            if token_full not in self.subscribed_tokens:
                self.subscribed_tokens.append(token_full)
        # ensure tick list exists in memory
        _, _, token_key = self._normalize_token(token_full)
        with self._tick_lock:
            self.tick_data.setdefault(token_key, [])
        # if connected, send subscription
        if self.ws_connected and self.ws_app:
            try:
                exch, token_id, _ = self._normalize_token(token_full)
                sub_msg = {"t": "t", "k": f"{exch}|{token_id}"}
                self.ws_app.send(json.dumps(sub_msg))
                print(f"✅ Subscribed (live) to {token_full}")
            except Exception as e:
                print("❌ Live subscribe failed:", e)

    def remove_subscription(self, token_full: str):
        with self._subscriptions_lock:
            try:
                self.subscribed_tokens.remove(token_full)
            except ValueError:
                pass
        # NOTE: most WS servers support unsubscribe; if supported, send unsub message here.
        # Example (if server supports t: "u"): self.ws_app.send(json.dumps({"t":"u","k": token_full}))

    # ----------------- Misc helpers -----------------
    def shutdown(self):
        """Convenience: stop websocket and join thread (not blocking forever)."""
        self.stop()
        if self.ws_thread:
            self.ws_thread.join(timeout=2.0)

    # ----------------- Optional REST helpers (login etc) -----------------
    # Included for completeness — adapt if you need REST login for jKey/session_token.
    def login_rest_quickauth(self, factor2_otp: str):
        """
        Example QuickAuth login (if you want to obtain a session token via HTTP).
        The code below mirrors common QuickAuth usage; adjust to your API details as needed.
        """
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = None
        if self.password_plain:
            import hashlib
            pwd_hash = hashlib.sha256(self.password_plain.encode()).hexdigest()
        appkey_hash = None
        if self.userid and self.api_key:
            import hashlib
            appkey_hash = hashlib.sha256(f"{self.userid}|{self.api_key}".encode()).hexdigest()

        payload = {
            "uid": self.userid,
            "pwd": pwd_hash or "",
            "factor2": factor2_otp or "",
            "vc": self.vc or "",
            "appkey": appkey_hash or "",
            "imei": self.imei or "",
            "apkversion": "1.0.0",
            "source": "API"
        }
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            resp = requests.post(url, data=raw_data, headers={"Content-Type": "text/plain"}, timeout=10)
            return resp.json()
        except Exception as e:
            return {"stat": "Not_Ok", "emsg": str(e)}


# ---------------- Example usage (comment out in production) ----------------
if __name__ == "__main__":
    # quick demo - connect, subscribe to token, run for some seconds then print recent ticks
    api = ProStocksAPI()
    api.start()  # starts WS run loop in background
    api.add_subscription("NSE|11872")
    print("Started WS and requested subscription; waiting for ticks...")
    try:
        # Let it run a while (replace with your app lifecycle)
        time.sleep(15)
        recent = api.get_recent_ticks("NSE|11872", n=20)
        print("Recent ticks (in-memory or CSV fallback):")
        for r in recent:
            print(r["ts"].isoformat(), r["price"], r["volume"])
    finally:
        api.shutdown()
        print("Stopped.")


# prostocks_connector.py
import os
import json
import time
import threading
import csv
import hashlib
from datetime import datetime
from typing import List, Optional, Dict, Any
import websocket
import requests
from pathlib import Path

# -- Configuration defaults --
DEFAULT_WS_URL = "wss://starapi.prostocks.com/NorenWSTP/"
TICKS_DIR = Path("./ticks")
TICKS_DIR.mkdir(parents=True, exist_ok=True)


class ProStocksAPI:
    """
    ProStocksAPI - focused on live tick subscription + tick persistence (no TPSeries).
    Added: send_otp() and login() for QuickAuth REST usage.
    """

    def __init__(self, userid: Optional[str] = None, password_plain: Optional[str] = None,
                 vc: Optional[str] = None, api_key: Optional[str] = None, imei: Optional[str] = None,
                 base_url: Optional[str] = None, apkversion: str = "1.0.0",
                 ws_url: str = DEFAULT_WS_URL, csv_dir: Path = TICKS_DIR):
        # Auth fields (optional)
        self.userid = userid
        self.password_plain = password_plain
        self.vc = vc
        self.api_key = api_key
        self.imei = imei
        self.apkversion = apkversion
        self.base_url = (base_url or "https://starapi.prostocks.com/NorenWClientTP").rstrip("/")

        # HTTP session for REST calls
        self.session = requests.Session()
        self.session_token: Optional[str] = None
        self.headers = {"Content-Type": "text/plain"}

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

    # ----------------- Auth helpers -----------------
    def sha256(self, text: str) -> str:
        return hashlib.sha256((text or "").encode()).hexdigest()

    def send_otp(self) -> Dict[str, Any]:
        """
        Trigger QuickAuth OTP (factor2 empty). Returns JSON response (may include emsg/stat).
        """
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain or "")
        appkey_hash = self.sha256(f"{self.userid}|{self.api_key}" if self.userid and self.api_key else "")
        payload = {
            "uid": self.userid or "",
            "pwd": pwd_hash,
            "factor2": "",
            "vc": self.vc or "",
            "appkey": appkey_hash,
            "imei": self.imei or "",
            "apkversion": self.apkversion or "1.0.0",
            "source": "API",
        }
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            resp = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            # return parsed JSON (or text parse error)
            try:
                return resp.json()
            except Exception:
                return {"stat": "Not_Ok", "emsg": resp.text}
        except requests.exceptions.RequestException as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    def login(self, factor2_otp: str) -> (bool, str):
        """
        Perform QuickAuth login with OTP (factor2). Returns (True, session_token) on success,
        else (False, error_message).
        """
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain or "")
        appkey_hash = self.sha256(f"{self.userid}|{self.api_key}" if self.userid and self.api_key else "")
        payload = {
            "uid": self.userid or "",
            "pwd": pwd_hash,
            "factor2": factor2_otp or "",
            "vc": self.vc or "",
            "appkey": appkey_hash,
            "imei": self.imei or "",
            "apkversion": self.apkversion or "1.0.0",
            "source": "API",
        }
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            resp = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            # try parse JSON
            try:
                data = resp.json()
            except Exception:
                return False, f"Non-JSON response: {resp.text}"

            if data.get("stat") == "Ok" or data.get("stat") == "OK":
                # Try to capture known token fields
                token = data.get("susertoken") or data.get("jKey") or data.get("token") or data.get("session")
                self.session_token = token
                if token:
                    # keep Authorization for any future REST calls (some endpoints expect jKey parameter instead)
                    self.headers["Authorization"] = token
                # update userid if server returned canonical uid
                if data.get("uid"):
                    self.userid = data.get("uid")
                return True, token or "OK"
            else:
                # return server error message
                return False, data.get("emsg") or data.get("error") or json.dumps(data)
        except requests.exceptions.RequestException as e:
            return False, str(e)

    # login_rest_quickauth kept for backward compatibility (alias)
    def login_rest_quickauth(self, factor2_otp: str):
        return self.login(factor2_otp)

    # ----------------- Utility helpers -----------------
    @staticmethod
    def _normalize_token(token_full: str):
        parts = token_full.split("|")
        if len(parts) == 2:
            exch, token_id = parts
        else:
            exch, token_id = "NSE", parts[0]
        token_key = token_id
        return exch, token_id, token_key

    def _csv_path_for_token(self, token_id: str) -> Path:
        return self.csv_dir / f"ticks_{token_id}.csv"

    def _append_tick_to_csv(self, token_full: str, token_id: str, ts: datetime, price: float, volume: int, raw: dict):
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
        token_full = raw_data.get("tk") or raw_data.get("token") or ""
        if not token_full:
            return

        exch, token_id, token_key = self._normalize_token(token_full)

        try:
            price = float(raw_data.get("lp", raw_data.get("tradeprice", 0) or 0.0))
        except Exception:
            price = 0.0
        try:
            volume = int(float(raw_data.get("v", raw_data.get("volume", 0) or 0)))
        except Exception:
            volume = 0

        ts = datetime.utcnow()
        tick_row = {"ts": ts, "price": price, "volume": volume, "raw": raw_data, "token_full": token_full}

        with self._tick_lock:
            lst = self.tick_data.setdefault(token_key, [])
            lst.append(tick_row)
            if len(lst) > self.max_in_memory_ticks:
                del lst[0: len(lst) - self.max_in_memory_ticks]

        try:
            self._append_tick_to_csv(token_full, token_key, ts, price, volume, raw_data)
        except Exception as e:
            print(f"⚠️ Failed appending tick to CSV for {token_key}: {e}")

    # ----------------- Historical loader & getters -----------------
    def load_historical_ticks(self, token_full: str, max_rows: Optional[int] = None) -> List[Dict[str, Any]]:
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
            if max_rows:
                rows = rows[-max_rows:]
            return rows
        except Exception as e:
            print(f"❌ Error loading historical ticks for {token_key}: {e}")
            return []

    def get_historical_ticks(self, token_full: str, start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[Dict[str, Any]]:
        rows = self.load_historical_ticks(token_full)
        if not rows:
            return []
        if start:
            rows = [r for r in rows if r["ts"] >= start]
        if end:
            rows = [r for r in rows if r["ts"] <= end]
        return rows

    def get_recent_ticks(self, token_full: str, n: int = 100) -> List[Dict[str, Any]]:
        _, token_id, token_key = self._normalize_token(token_full)
        with self._tick_lock:
            buf = list(self.tick_data.get(token_key, []))
        if buf:
            return buf[-n:]
        return self.load_historical_ticks(token_full, max_rows=n)

    # ----------------- WebSocket lifecycle -----------------
    def _on_ws_message(self, ws, message):
        try:
            data = json.loads(message)
        except Exception:
            return
        if data.get("t") == "tk" or data.get("type") == "tick" or "lp" in data:
            self.on_tick(data)
        else:
            if data.get("s") == "OK":
                print(f"WS subscription ack: {data}")

    def _on_ws_open(self, ws):
        print("🔗 WebSocket opened")
        self.ws_connected = True
        self._reconnect_backoff = 1.0
        time.sleep(0.2)
        with self._subscriptions_lock:
            for token in self.subscribed_tokens:
                try:
                    exch, token_id, _ = self._normalize_token(token)
                    sub_msg = {"t": "t", "k": f"{exch}|{token_id}"}
                    ws.send(json.dumps(sub_msg))
                    print(f"✅ Sent subscription: {sub_msg}")
                except Exception as e:
                    print("❌ Failed send subscription:", e)

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
        if not self._stop_event.is_set():
            threading.Thread(target=self._reconnect_loop, daemon=True).start()

    def _on_ws_error(self, ws, error):
        print("❌ WebSocket error:", error)

    def _run_ws(self):
        self.ws_app = websocket.WebSocketApp(
            self.ws_url,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
        )
        try:
            self.ws_app.run_forever(ping_interval=self.ping_interval, ping_timeout=10)
        except Exception as e:
            print("❌ run_forever ended with exception:", e)
        finally:
            self.ws_connected = False

    def start(self, background: bool = True):
        self._stop_event.clear()
        if self.ws_thread and self.ws_thread.is_alive():
            return
        self.ws_thread = threading.Thread(target=self._run_ws, daemon=True)
        self.ws_thread.start()
        self._reconnect_backoff = 1.0

    def stop(self):
        self._stop_event.set()
        try:
            if self.ws_app:
                self.ws_app.close()
        except Exception:
            pass
        self.ws_connected = False

    def _reconnect_loop(self):
        if self._stop_event.is_set():
            return
        wait = self._reconnect_backoff
        print(f"🔁 Reconnect in {wait:.1f}s...")
        time.sleep(wait)
        self._reconnect_backoff = min(self._reconnect_backoff * 2.0, 60.0)
        if self._stop_event.is_set():
            return
        try:
            self.start(background=True)
        except Exception as e:
            print("❌ Reconnect start failed:", e)

    # ----------------- Subscription management -----------------
    def add_subscription(self, token_full: str):
        with self._subscriptions_lock:
            if token_full not in self.subscribed_tokens:
                self.subscribed_tokens.append(token_full)
        _, _, token_key = self._normalize_token(token_full)
        with self._tick_lock:
            self.tick_data.setdefault(token_key, [])
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

    def shutdown(self):
        self.stop()
        if self.ws_thread:
            self.ws_thread.join(timeout=2.0)


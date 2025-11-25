
#!/usr/bin/env python3
"""
LIVE TICK ENGINE
----------------
✔ Fetch TPSeries (60 days)
✔ Subscribe ProStocks WS ticks for all tokens
✔ Build LIVE candles (1m)
✔ Merge TPSeries + live candle
✔ Save final dataframe per symbol
✔ Accessible to Auto Trader Worker
"""

import json
import os
import time
from datetime import datetime

import pandas as pd
import pytz
import requests

from prostocks_connector import ProStocksAPI

import websocket
import threading

BACKEND_URL = os.environ.get("BACKEND_URL", "https://backend-stream-nmlf.onrender.com")

SAVE_PATH = "/tmp/live_candles"
os.makedirs(SAVE_PATH, exist_ok=True)

IST = pytz.timezone("Asia/Kolkata")


# -----------------------------------------------------------
# 1) Load full TPSeries (backfill)
# -----------------------------------------------------------
def load_backfill(ps_api, exch, token, interval="1"):
    df = ps_api.fetch_full_tpseries(exch, token, interval)
    if df is None or isinstance(df, dict) or df.empty:
        return pd.DataFrame()

    # ✅ Always parse as UTC, then convert to IST
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce", utc=True)
    df["datetime"] = df["datetime"].dt.tz_convert(IST)

    df = df.sort_values("datetime")
    return df

# -----------------------------------------------------------
# 2) Build LIVE candles from ticks
# -----------------------------------------------------------
class CandleBuilder:
    def __init__(self):
        # key = (symbol, minute)
        self.candles = {}

    def update_tick(self, symbol, ltp, volume, ts):
        ts = datetime.fromtimestamp(ts, tz=IST)
        minute = ts.replace(second=0, microsecond=0)

        key = (symbol, minute)

        if key not in self.candles:
            self.candles[key] = {
                "datetime": minute,
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "volume": volume
            }
        else:
            c = self.candles[key]
            c["high"] = max(c["high"], ltp)
            c["low"] = min(c["low"], ltp)
            c["close"] = ltp
            c["volume"] += volume

    def get_latest(self, symbol):
        latest_keys = [k for k in self.candles.keys() if k[0] == symbol]
        if not latest_keys:
            return None

        latest_key = sorted(latest_keys, key=lambda x: x[1])[-1]
        return self.candles[latest_key]


candle_builder = CandleBuilder()


# -----------------------------------------------------------
# 3) Merge TPSeries + LIVE candle
# -----------------------------------------------------------
def merge_candles(df_tp, live_candle):
    df = df_tp.copy()

    if live_candle:
        # last TPSeries candle हटाकर latest live candle जोड़ते हैं
        df = df[df["datetime"] < live_candle["datetime"]]
        df = pd.concat([df, pd.DataFrame([live_candle])], ignore_index=True)

    return df


# -----------------------------------------------------------
# 4) SAVE LOOP – har 3 sec me JSON files update
# -----------------------------------------------------------
def save_loop(token_map):
    """Periodically merge TPSeries + LIVE candle and save to /tmp/live_candles"""
    global cached_tp
    print("🧾 Save loop started (every 3 sec)...")
    last_merge = 0

    while True:
        try:
            if time.time() - last_merge > 3:
                last_merge = time.time()

                for sym, tkn in token_map.items():
                    fn = os.path.join(SAVE_PATH, f"{sym}.json")

                    df_tp = cached_tp.get(sym)
                    live_c = candle_builder.get_latest(sym)

                    try:
                        if df_tp is not None and not df_tp.empty:
                            df_final = merge_candles(df_tp, live_c)
                        elif live_c:
                            df_final = pd.DataFrame([live_c])
                        else:
                            df_final = pd.DataFrame()

                        if not df_final.empty:
                            df_final.to_json(fn, orient="records", date_format="iso")
                    except Exception as e:
                        print(f"⚠️ Error saving {sym}: {e}")

        except Exception as e:
            print(f"⚠️ save_loop error: {e}")

        time.sleep(1)


# -----------------------------------------------------------
# 5) ProStocks DIRECT WebSocket – ALL symbols
# -----------------------------------------------------------
def start_prostocks_ws(ps_api, token_map):
    print("🔥🔥 ENTERED start_prostocks_ws() 🔥🔥")
    print("DEBUG: Token map size =", len(token_map))

    """
    🔥 Direct ProStocks WebSocket for ALL symbols
    """

    WS_URL = "wss://starapi.prostocks.com/NorenWSTP/"

    # ==============================
    #  ✅ BATCH SUBSCRIBE HELPER
    # ==============================
    def subscribe_in_batches(ws, batch_size=25, delay=1.0):
        items = list(token_map.items())
        print(f"🚀 Batch subscribing {len(items)} symbols...")

        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]

            for sym, tok in batch:
                if not tok:
                    continue

                msg = {
                    "t": "t",
                    "k": f"NSE|{tok}"
                }
                ws.send(json.dumps(msg))
                # print(f"📡 Subscribed: {sym} | {tok}")

            print(f"✅ Subscribed batch {i+1} → {i+len(batch)}")
            time.sleep(delay)

    # ==============================
    #  ✅ on_open → sirf LOGIN
    # ==============================
    def on_open(ws):
        print("🔥🔥 on_open ENTERED 🔥🔥")
        print("✅ ProStocks WS TCP Connected — sending login...")

        try:
            uid = getattr(ps_api, "uid", None) or getattr(ps_api, "userid", None)
            actid = getattr(ps_api, "actid", None) or uid

            login_msg = {
                "t": "c",
                "uid": uid,
                "actid": actid,
                "susertoken": ps_api.session_token,   # ✅ THIS IS THE FIX
                "source": "API"
            }

            print("LOGIN PAYLOAD =")
            print(json.dumps(login_msg, indent=2))

            ws.send(json.dumps(login_msg))
            print("📨 WS login sent")

            # ✅ wait for login handshake
            time.sleep(1)

            print("⚡ TEST SUBSCRIBE : NSE|3045 (SBIN)")
            ws.send(json.dumps({
                "t": "t",
                "k": "NSE|3045"
            }))

            print("✅ SBIN subscribe sent")

        except Exception as e:
            print("⚠️ Failed to send WS login:", e)

    # ==============================
    #  ✅ on_message → ck + ticks
    # ==============================
    def on_message(ws, message):
        print("\n📩 FROM WS >>>", message, "\n")
        try:
            data = json.loads(message)

            # 🔎 LOGIN RESPONSE (ck)
            if data.get("t") == "ck":
                print("🔔 WS ck message:", data)

                # ✅ LOGIN OK → ab batch subscribe
                if data.get("s") == "OK":
                    print("✅ WS LOGIN OK — starting batch subscribe...")
                    subscribe_in_batches(ws)
                else:
                    print("❌ WS LOGIN NOT_OK — jKey / creds check karo")

                return

            # 🔎 Heartbeat / other non-tick messages
            if data.get("t") != "tk":
                print("ℹ️ Non-tick WS msg:", data)
                return

            # ==========================
            #  ✅ TICK PARSE
            # ==========================
            token = data.get("tk")
            ltp = data.get("fp") or data.get("lp")
            vol = data.get("v") or 0
            ts = data.get("ft") or int(time.time())

            if not token or not ltp:
                return

            try:
                ltp = float(ltp)
                vol = int(vol)
                ts = int(ts)
            except:
                return

            # map token -> symbol
            symbol = None
            for s, t in token_map.items():
                if str(t) == str(token):
                    symbol = s
                    break

            if not symbol:
                return

            # ✅ update candle
            candle_builder.update_tick(symbol, ltp, vol, ts)

        except Exception as e:
            print("❌ WS Message Error:", e)

    def on_error(ws, error):
        print("❌ WebSocket Error:", error)

    def on_close(ws, close_status_code, close_msg):
        print("⚠️ ProStocks WS closed… reconnecting in 5s")
        time.sleep(5)
        start_prostocks_ws(ps_api, token_map)

    # ✅ WebSocket client
    ws = websocket.WebSocketApp(
        WS_URL,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )

    # ✅ Keepalive with ping
    ws.run_forever(ping_interval=10, ping_timeout=5)

# -----------------------------------------------------------
# 6) ENTRY POINT
# -----------------------------------------------------------
if __name__ == "__main__":

    # ---- 1) Load session + tokens from backend ----
    print("🔍 Fetching session_info from backend...")
    try:
        resp = requests.get(f"{BACKEND_URL}/session_info", timeout=25)
        session_info = resp.json()
    except Exception as e:
        print("❌ Could not load session_info from backend:", e)
        exit(1)

    session_token = session_info.get("session_token")
    token_map = session_info.get("tokens_map", {})
    userid = session_info.get("userid")

    # ✅ ADD THESE 3 LINES
    vc      = session_info.get("vc") or os.environ.get("VC")
    api_key = session_info.get("api_key") or os.environ.get("API_KEY")
    imei    = session_info.get("imei") or os.environ.get("IMEI")

    if not session_token or not token_map or not userid:
        print("❌ No session or tokens or userid from backend — cannot continue.")
        print("👉 Fix: Tab-3 open karke watchlist load karo, phir Tab-4 se backend /init run karo.")
        exit(1)

    print(f"✔ Session OK, userid={userid}, tokens={len(token_map)}")

    # ---- 2) Create ps_api WITHOUT login (reuse backend session) ----
    base_url = os.environ.get(
        "BASE_URL",
        "https://starapi.prostocks.com/NorenWClientTP"
    )

    ps_api = ProStocksAPI(
        userid=userid,
        password_plain="",
        vc=vc,
        api_key=api_key,
        imei=imei,
        base_url=base_url
    )

    # Inject backend session
    ps_api.session_token = session_token
    ps_api.jKey = session_token
    ps_api.uid = userid
    ps_api.actid = userid
    ps_api.logged_in = True
    ps_api.is_logged_in = True
    ps_api.is_session_active = True

    ps_api.headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": session_token
    }

    print("✔ Backend session attached. Loading TPSeries…")

    # ---- 3) Preload TPSeries for all symbols ----
    # ---- 3) Preload TPSeries for all symbols (BACKGROUND THREAD) ----
    global cached_tp
    cached_tp = {}

    def preload_all_tpseries(ps_api, token_map):
        global cached_tp
        print("📥 Background TPSeries loading started...")
        print("🚀 Token count =", len(token_map))

        for sym, token in token_map.items():
            try:
                df_tp = load_backfill(ps_api, "NSE", token, interval="5")

                if df_tp is None or df_tp.empty:
                    print(f"⚠️ {sym} backfill empty")
                else:
                    cached_tp[sym] = df_tp
                    print(f"✅ {sym} backfill loaded: {len(df_tp)} candles")

            except Exception as e:
                print(f"❌ Error loading TPSeries for {sym}: {e}")

        print("✅✅ TPSeries preload FINISHED ✅✅")


    
    print("🔥 STARTING PROSTOCKS WS THREAD")
    threading.Thread(
        target=start_prostocks_ws,
        args=(ps_api, token_map),
        daemon=True
    ).start()

    time.sleep(5)   # ✅ WS ko head-start

    print("🔥 STARTING SAVE LOOP")
    threading.Thread(
        target=save_loop,
        args=(token_map,),
        daemon=True
    ).start()

    time.sleep(3)

    print("🔥 STARTING TPSeries preload thread")
    threading.Thread(
        target=preload_all_tpseries,
        args=(ps_api, token_map),
        daemon=True
    ).start()

    print("🔁 Tick engine running...")
    while True:
        time.sleep(5)

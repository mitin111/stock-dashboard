
# prostocks_connector.py
import requests
import hashlib
import json
import os
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta
import websocket
import threading
import pandas as pd

load_dotenv()


class ProStocksAPI:
    def __init__(
        self,
        userid=None,
        password_plain=None,
        vc=None,
        api_key=None,
        imei=None,
        base_url=None,
        apkversion="1.0.0"
    ):
        self.userid = userid or os.getenv("PROSTOCKS_USER_ID")
        self.password_plain = password_plain or os.getenv("PROSTOCKS_PASSWORD")
        self.vc = vc or os.getenv("PROSTOCKS_VENDOR_CODE")
        self.api_key = api_key or os.getenv("PROSTOCKS_API_KEY")
        self.imei = imei or os.getenv("PROSTOCKS_MAC")
        self.base_url = (base_url or os.getenv("PROSTOCKS_BASE_URL")).rstrip("/")
        self.apkversion = apkversion
        self.session_token = None
        self.session = requests.Session()
        self.headers = {
            "Content-Type": "text/plain"
        }

        self.credentials = {
            "uid": self.userid,
            "pwd": self.password_plain,
            "vc": self.vc,
            "api_key": self.api_key,
            "imei": self.imei
        }

    def sha256(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    def send_otp(self):
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_raw = f"{self.userid}|{self.api_key}"
        appkey_hash = self.sha256(appkey_raw)

        payload = {
            "uid": self.userid,
            "pwd": pwd_hash,
            "factor2": "",
            "vc": self.vc,
            "appkey": appkey_hash,
            "imei": self.imei,
            "apkversion": self.apkversion,
            "source": "API"
        }

        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            response = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            print("📨 OTP Trigger Response:", response.text)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"emsg": str(e)}

    def login(self, factor2_otp):
        url = f"{self.base_url}/QuickAuth"
        pwd_hash = self.sha256(self.password_plain)
        appkey_raw = f"{self.userid}|{self.api_key}"
        appkey_hash = self.sha256(appkey_raw)

        payload = {
            "uid": self.userid,
            "pwd": pwd_hash,
            "factor2": factor2_otp,
            "vc": self.vc,
            "appkey": appkey_hash,
            "imei": self.imei,
            "apkversion": self.apkversion,
            "source": "API"
        }

        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}"
            response = self.session.post(url, data=raw_data, headers=self.headers, timeout=10)
            print("🔁 Login Response Code:", response.status_code)
            print("📨 Login Response Body:", response.text)

            if response.status_code == 200:
                data = response.json()
                if data.get("stat") == "Ok":
                    self.session_token = data["susertoken"]
                    self.userid = data["uid"]
                    self.headers["Authorization"] = self.session_token
                    print("✅ Login Success!")
                    return True, self.session_token
                else:
                    return False, data.get("emsg", "Unknown login error")
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"RequestException: {e}"

    # === Watchlist APIs ===

    def get_watchlists(self):
        url = f"{self.base_url}/MWList"
        payload = {"uid": self.userid}
        return self._post_json(url, payload)

    def get_watchlist_names(self):
        resp = self.get_watchlists()
        if resp.get("stat") == "Ok":
            return sorted(resp["values"], key=int)
        return []

    def get_watchlist(self, wlname):
        url = f"{self.base_url}/MarketWatch"
        payload = {"uid": self.userid, "wlname": wlname}
        return self._post_json(url, payload)

    def search_scrip(self, search_text, exch="NSE"):
        url = f"{self.base_url}/SearchScrip"
        payload = {"uid": self.userid, "stext": search_text, "exch": exch}
        return self._post_json(url, payload)

    def add_scrips_to_watchlist(self, wlname, scrips_list):
        url = f"{self.base_url}/AddMultiScripsToMW"
        scrips_str = ",".join(scrips_list)
        payload = {"uid": self.userid, "wlname": wlname, "scrips": scrips_str}
        return self._post_json(url, payload)

    def delete_scrips_from_watchlist(self, wlname, scrips_list):
        url = f"{self.base_url}/DeleteMultiMWScrips"
        scrips_str = ",".join(scrips_list)
        payload = {"uid": self.userid, "wlname": wlname, "scrips": scrips_str}
        return self._post_json(url, payload)

    # === Internal Helper ===

    def _post_json(self, url, payload):
        if not self.session_token:
            return {"stat": "Not_Ok", "emsg": "Not Logged In. Session Token Missing."}
        try:
            jdata = json.dumps(payload, separators=(",", ":"))
            raw_data = f"jData={jdata}&jKey={self.session_token}"
            print("✅ POST URL:", url)
            print("📦 Sent Payload:", jdata)

            response = self.session.post(
                url,
                data=raw_data,
                headers={"Content-Type": "text/plain"},
                timeout=10
            )
            print("📨 Response:", response.text)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

# -------------------------
# USER CONFIG (fill these)
# -------------------------
BASE_URL = "https://starapi.prostocks.com"  # or UAT: https://starapiuat.prostocks.com
TPSERIES_PATH = "/NorenWClientTP/TPSeries"
WS_URL = "wss://starapi.prostocks.com/NorenWSTP/"  # update if using UAT

# NOTE: you'll typically obtain jKey after login. For demo fill in via UI.

# -------------------------
# Utility functions
# -------------------------

def to_unix_seconds(dt: datetime) -> int:
    return int(dt.timestamp())


def fetch_tpseries(jkey, uid, exch, token, st_ts, et_ts, intrv='1'):
    """
    Call TPSeries endpoint. Returns list of dicts (or raises on error).
    Payload: jData = JSON string with uid, exch, token, st, et, intrv
    """
    url = BASE_URL + TPSERIES_PATH
    jdata = {
        "uid": uid,
        "exch": exch,
        "token": token,
        "st": int(st_ts),
        "et": int(et_ts),
        "intrv": str(intrv)
    }
    # Many brokers expect form-encoded data: jData (string) and jKey
    payload = {
        'jData': json.dumps(jdata),
        'jKey': jkey
    }
    headers = {
        'User-Agent': 'prostocks-tpseries-client'
    }
    resp = requests.post(url, data=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"Invalid JSON from TPSeries: {e} - text={resp.text}")

    # If failure format
    if isinstance(data, dict) and data.get('stat') == 'Not_Ok':
        raise RuntimeError(f"TPSeries error: {data.get('emsg')}")

    return data


# -------------------------
# Candle builder utilities
# -------------------------

def make_empty_candle(ts, intrv_minutes):
    return {
        'time': ts,  # datetime
        'open': None,
        'high': None,
        'low': None,
        'close': None,
        'volume': 0
    }


def update_candle_with_tick(candle, tick_price, tick_volume=0):
    if candle['open'] is None:
        candle['open'] = tick_price
        candle['high'] = tick_price
        candle['low'] = tick_price
        candle['close'] = tick_price
    else:
        candle['high'] = max(candle['high'], tick_price)
        candle['low'] = min(candle['low'], tick_price)
        candle['close'] = tick_price
    candle['volume'] = candle.get('volume', 0) + int(tick_volume or 0)


# -------------------------
# WebSocket handling (runs in background thread)
# -------------------------

class TickWebsocket:
    def __init__(self, ws_url, subscribe_tokens, on_tick_callback, headers=None):
        self.ws_url = ws_url
        self.subscribe_tokens = subscribe_tokens  # list of strings like "NSE|22"
        self.on_tick = on_tick_callback
        self.headers = headers or {}
        self.ws = None
        self.thread = None
        self.running = False

    def ws_on_open(self, ws):
        st = time.strftime('%d-%m-%Y %H:%M:%S')
        print('WebSocket opened at', st)
        # Send subscription - format may vary; update if your broker requires a different payload
        # Many brokers expect something like: {"type":"subscribe","symbols":["NSE|22"]}
        sub_msg = self.ws_subscribe_message()
        print('Sending subscribe message:', sub_msg)
        ws.send(sub_msg)

    def ws_on_message(self, ws, message):
        # message format depends on server. We'll attempt to parse JSON and extract a price
        try:
            msg = json.loads(message)
        except Exception:
            # not JSON -- ignore
            return

        # Typical tick payloads may include fields: 'lp' (last price), 'v' (volume), 'exch', 'tk' or 'token'
        # We'll try a few common keys.
        tick_price = None
        tick_volume = 0
        token = None

        # try common shapes
        if isinstance(msg, dict):
            # sometimes wrapped like {"values":[{...}]}
            if 'values' in msg and isinstance(msg['values'], list) and len(msg['values'])>0:
                item = msg['values'][0]
                tick_price = item.get('lp') or item.get('ltp') or item.get('last_price') or item.get('lp1')
                tick_volume = item.get('v') or item.get('volume') or item.get('vol') or 0
                token = item.get('token') or item.get('tk') or item.get('token_id')
            else:
                tick_price = msg.get('lp') or msg.get('ltp') or msg.get('last_price')
                tick_volume = msg.get('v') or msg.get('volume') or 0
                token = msg.get('token') or msg.get('tk')

        # final safety: if we couldn't find price, ignore
        if tick_price is None:
            return

        try:
            price = float(tick_price)
        except Exception:
            return

        try:
            vol = int(tick_volume) if tick_volume is not None else 0
        except Exception:
            vol = 0

        # Call user callback
        self.on_tick({
            'price': price,
            'volume': vol,
            'token': token,
            'raw': msg,
            'ts': time.time()
        })

    def ws_on_error(self, ws, error):
        print('Websocket error:', error)

    def ws_on_close(self, ws, close_status_code, close_msg):
        print('Websocket closed', close_status_code, close_msg)
        self.running = False

    def ws_subscribe_message(self):
        # Adjust this depending on your broker's websocket subscribe format.
        # Example format used by some ProStocks wrappers: "{\"action\":\"subscribe\",\"symbols\":[\"NSE|22\"]}"
        msg = {"action": "subscribe", "symbols": self.subscribe_tokens}
        return json.dumps(msg)

    def start(self):
        self.running = True
        self.ws = WebSocketApp(self.ws_url,
                               header=[f"{k}: {v}" for k, v in (self.headers or {}).items()],
                               on_open=self.ws_on_open,
                               on_message=self.ws_on_message,
                               on_error=self.ws_on_error,
                               on_close=self.ws_on_close)

        def run_ws():
            # will block until closed
            self.ws.run_forever()

        self.thread = threading.Thread(target=run_ws, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass


# -------------------------
# Streamlit App
# -------------------------

st.set_page_config(page_title='ProStocks TPSeries + Live Candles', layout='wide')
st.title('ProStocks: 60-day TPSeries + Live Candle Chart')

with st.sidebar:
    st.header('Connection / Settings')
    base_url_input = st.text_input('Base URL', value=BASE_URL)
    ws_url_input = st.text_input('WebSocket URL', value=WS_URL)
    jkey = st.text_input('jKey (from login)', value='', type='password')
    uid = st.text_input('UID (user id)', value='')
    exch = st.selectbox('Exchange', ['NSE', 'BSE', 'NFO'], index=0)
    token = st.text_input('Token (e.g., 22 for RELIANCE)', value='22')
    intrv = st.selectbox('Interval (minutes)', ['1','3','5','10','15','30','60'], index=2)
    days_back = st.number_input('Days historical (max 60 suggested)', min_value=1, max_value=365, value=60)
    subscribe_checkbox = st.checkbox('Use WebSocket live ticks to update candles', value=True)
    start_btn = st.button('Fetch & Start')

# Keep state for candles
if 'candles_df' not in st.session_state:
    st.session_state.candles_df = pd.DataFrame()

if 'ws_client' not in st.session_state:
    st.session_state.ws_client = None

if start_btn:
    # update globals from inputs
    BASE_URL = base_url_input.strip()
    WS_URL = ws_url_input.strip()

    if not jkey or not uid:
        st.error('Please provide jKey and UID (login).')
    else:
        st.info('Fetching historical data...')
        et = int(time.time())
        st_ts = et - int(days_back * 24 * 60 * 60)

        try:
            data = fetch_tpseries(jkey=jkey, uid=uid, exch=exch, token=token, st_ts=st_ts, et_ts=et, intrv=intrv)
        except Exception as e:
            st.error(f'Failed to fetch TPSeries: {e}')
            data = None

        if data:
            # convert to DataFrame and normalize
            rows = []
            # expected fields: time, into (open), inth (high), intl (low), intc (close), intv (vol)
            for item in data:
                if item.get('stat') != 'Ok':
                    continue
                tstr = item.get('time')
                # try multiple time formats
                try:
                    dt = datetime.strptime(tstr, '%d-%m-%Y %H:%M:%S')
                except Exception:
                    try:
                        dt = datetime.strptime(tstr, '%d/%m/%Y %H:%M:%S')
                    except Exception:
                        dt = None

                rows.append({
                    'time': dt,
                    'open': float(item.get('into', 0) or 0),
                    'high': float(item.get('inth', 0) or 0),
                    'low': float(item.get('intl', 0) or 0),
                    'close': float(item.get('intc', 0) or 0),
                    'volume': int(float(item.get('intv', 0) or 0))
                })

            df = pd.DataFrame(rows)
            df = df.dropna(subset=['time']).sort_values('time')
            df = df.reset_index(drop=True)

            st.session_state.candles_df = df
            st.success(f'Historical candles fetched: {len(df)} rows')

        # start websocket if requested
        if subscribe_checkbox:
            st.info('Starting websocket client...')

            # create a simple on_tick handler that updates session_state candles
            intrv_min = int(intrv)

            # keep a small local mutable state for current candle
            candle_state = {'current_candle': None}

            def on_tick(tick):
                # tick: {price, volume, token, ts}
                price = tick['price']
                ts = datetime.fromtimestamp(tick['ts'])

                # compute candle timestamp by flooring to interval
                floored_min = (ts.minute // intrv_min) * intrv_min
                candle_ts = ts.replace(second=0, microsecond=0, minute=floored_min)

                # if no candles yet, create from historical
                if st.session_state.candles_df.empty:
                    # create one to begin
                    c = make_empty_candle(candle_ts, intrv_min)
                    update_candle_with_tick(c, price, tick.get('volume', 0))
                    st.session_state.candles_df = pd.DataFrame([{
                        'time': c['time'], 'open': c['open'], 'high': c['high'], 'low': c['low'], 'close': c['close'], 'volume': c['volume']
                    }])
                    return

                last_time = st.session_state.candles_df['time'].iloc[-1]
                if candle_ts > last_time:
                    # finalize previous candle (already in df) and append new candle
                    c = make_empty_candle(candle_ts, intrv_min)
                    update_candle_with_tick(c, price, tick.get('volume', 0))
                    new_row = {'time': c['time'], 'open': c['open'], 'high': c['high'], 'low': c['low'], 'close': c['close'], 'volume': c['volume']}
                    st.session_state.candles_df = pd.concat([st.session_state.candles_df, pd.DataFrame([new_row])], ignore_index=True)
                else:
                    # update last candle
                    idx = len(st.session_state.candles_df) - 1
                    row = st.session_state.candles_df.loc[idx]
                    candle = {'time': row['time'], 'open': row['open'], 'high': row['high'], 'low': row['low'], 'close': row['close'], 'volume': row['volume']}
                    update_candle_with_tick(candle, price, tick.get('volume', 0))
                    for k in ['open','high','low','close','volume']:
                        st.session_state.candles_df.at[idx, k] = candle[k]

            # headers for ws if needed (token-based auth). Example header: Authorization: Bearer <access_token>
            ws_headers = {}
            # If your environment requires special headers (Access_token, UID, Account_ID), add them here
            # ws_headers = { 'Authorization': 'Bearer <ACCESS_TOKEN>', 'UID': uid }

            # create and start client
            subscribe_tokens = [f"{exch}|{token}"]
            ws_client = TickWebsocket(ws_url=WS_URL, subscribe_tokens=subscribe_tokens, on_tick_callback=on_tick, headers=ws_headers)
            ws_client.start()
            st.session_state.ws_client = ws_client

# Chart display
chart_placeholder = st.empty()

# Render loop: update every 1.5 seconds while websocket running or until user stops
if not st.session_state.candles_df.empty:
    df_chart = st.session_state.candles_df.copy()
    # convert time to string for plotly
    df_chart['time_str'] = df_chart['time'].dt.strftime('%Y-%m-%d %H:%M:%S')

    fig = go.Figure(data=[go.Candlestick(
        x=df_chart['time_str'], open=df_chart['open'], high=df_chart['high'], low=df_chart['low'], close=df_chart['close'], name='Candles'
    )])
    fig.update_layout(xaxis_rangeslider_visible=False, height=600)
    chart_placeholder.plotly_chart(fig, use_container_width=True)

    # Auto-update area
    if subscribe_checkbox and st.session_state.ws_client is not None:
        st.info('Live updates enabled. Chart will refresh while websocket runs in background.')

        # simple refresh loop using st.experimental_rerun is too heavy; instead rely on a short sleep + rerun
        # We'll provide a manual Refresh button to avoid infinite reruns in deployment
        if st.button('Refresh Chart Now'):
            st.experimental_rerun()
    else:
        st.write('WebSocket not started. Use "Use WebSocket" and click "Fetch & Start" to enable live updates.')

# Stop websocket button
if st.button('Stop WebSocket'):
    if st.session_state.ws_client:
        st.session_state.ws_client.stop()
        st.session_state.ws_client = None
        st.success('WebSocket stopped.')

st.markdown('---')
st.caption('Notes: You may need to adapt WS subscription message and authentication headers depending on your ProStocks account (UAT vs LIVE).')



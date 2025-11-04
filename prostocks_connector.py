# prostocks_connector.py
import requests
import hashlib
import json
import os
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import pandas as pd
import websocket
import threading
import queue

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
        self.headers = {"Content-Type": "text/plain"}

        self.credentials = {
            "uid": self.userid,
            "pwd": self.password_plain,
            "vc": self.vc,
            "api_key": self.api_key,
            "imei": self.imei
        }

        # --- WebSocket state ---
        self.ws = None
        self.is_ws_connected = False
        self._sub_tokens = []
        self.tick_file = "ticks.log"
        self.ws_url = "wss://starapi.prostocks.com/NorenWSTP/"

        # ✅ Tick Queue + File init YAHAN karna hai
        import queue
        self._tokens = {}  # symbol → token mapping
        self.tick_queue = queue.Queue()
        self.tick_file = "ticks.log"

        self.candles = {}

    # ---------------- Utils ----------------
    def sha256(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    # ---------------- Auth ----------------
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
                    self.jKey = self.session_token   # ✅ fix for scripts using ps_api.jKey
                    self.userid = data["uid"]
                    self.actid = data["uid"]   # <-- add this
                    self.headers["Authorization"] = self.session_token
                    print(f"✅ Login Success! Session token set: {self.session_token[:8]}...")
                    return True, self.session_token
                else:
                    return False, data.get("emsg", "Unknown login error")
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"RequestException: {e}"

    # ------------- Core POST helper -------------
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
                timeout=15
            )
            print("📨 Response:", response.text)
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    # ------------- Watchlists -------------
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

    
    # --- ADD HERE ---
    def get_token(self, symbol, exch="NSE"):
        token = self._tokens.get(symbol)
        if not token:
            print(f"⚠️ Token not found for {symbol}. Please fetch/populate _tokens first.")
        return token

    def fetch_watchlist_tokens(self, wlname):
        """
        Fetch symbols from a watchlist and populate self._tokens
        """
        wl = self.get_watchlist(wlname)
        if not wl or "values" not in wl:
            print(f"⚠️ No symbols found in watchlist {wlname}")
            return []

        for s in wl["values"]:
            sym = s.get("tsym")
            tok = s.get("token")
            exch = s.get("exch", "NSE")
            if sym and tok:
                self._tokens[sym] = tok

        print(f"✅ _tokens populated from watchlist {wlname}: {list(self._tokens.keys())}")
        return list(self._tokens.keys())


    def get_quotes(self, symbol, exch="NSE", wlname=None):
        token = self._tokens.get(symbol)

        # Auto-fetch token from watchlist if missing
        if not token and wlname:
            self.fetch_watchlist_tokens(wlname)
            token = self._tokens.get(symbol)

        if not token:
            return {"stat": "Not_Ok", "emsg": f"Token not found for {symbol}"}

        uid = getattr(self, "userid", None)
        jKey = getattr(self, "jKey", None)

        if not uid or not jKey:
            return {"stat": "Not_Ok", "emsg": "uid or jKey missing"}

        payload = {"uid": uid, "exch": exch, "token": token}
        data = f"jData={json.dumps(payload, separators=(',', ':'))}&jKey={jKey}"

        try:
            resp = self.session.post(
                f"{self.base_url}/NorenWClientTP/GetQuotes",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10
            )

            # ✅ Step 2 patch: handle empty or invalid response
            if not resp.text.strip():
                print(f"⚠️ Empty GetQuotes response for {symbol}")
                return {"stat": "Exception", "emsg": "Empty response from server"}

            try:
                jresp = resp.json()
            except Exception as e:
                print(f"⚠️ Invalid JSON in GetQuotes for {symbol}: {e} | Raw: {resp.text[:200]}")
                return {"stat": "Exception", "emsg": f"Invalid JSON: {e}"}

            if jresp.get("stat") != "Ok":
                print(f"⚠️ GetQuotes error for {symbol}: {jresp.get('emsg')}")
                return jresp

            return jresp

        except Exception as e:
            return {"stat": "Exception", "emsg": str(e)}

       # ------------- TPSeries -------------
    def get_tpseries(self, exch, token, interval="5", st=None, et=None):
        """
        Returns raw TPSeries from API.
        For success, the API typically returns a list; on error it returns a dict with 'stat'/'emsg'.
        'st' and 'et' must be epoch seconds (UTC).
        """
        if not self.session_token:
            return {"stat": "Not_Ok", "emsg": "Session token missing. Please login again."}

        # Default window (last 60 days) if not provided
        if st is None or et is None:
            days_back = 60
            et_dt = datetime.now(timezone.utc)
            st_dt = et_dt - timedelta(days=days_back)
            st = int(st_dt.timestamp())
            et = int(et_dt.timestamp())

        url = f"{self.base_url}/TPSeries"
        payload = {
            "uid": self.userid,
            "exch": exch,
            "token": str(token),
            "st": str(st),
            "et": str(et),
            "intrv": str(interval)
        }

        print("📤 Sending TPSeries Payload:")
        print(f"  UID    : {payload['uid']}")
        print(f"  EXCH   : {payload['exch']}")
        print(f"  TOKEN  : {payload['token']}")
        print(f"  ST     : {payload['st']} → {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int(st)))} UTC")
        print(f"  ET     : {payload['et']} → {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int(et)))} UTC")
        print(f"  INTRV  : {payload['intrv']}")

        try:
            response = self._post_json(url, payload)
            return response
        except Exception as e:
            print("❌ Exception in get_tpseries():", e)
            return {"stat": "Not_Ok", "emsg": str(e)}


    # ---------------- TPSeries fetch ----------------
    def fetch_full_tpseries(self, exch, token, interval="5", chunk_days=5, max_days=60):
        all_chunks = []
        end_dt = datetime.now(timezone.utc)
        start_limit_dt = end_dt - timedelta(days=max_days)

        while end_dt > start_limit_dt:
            start_dt = end_dt - timedelta(days=chunk_days)
            if start_dt < start_limit_dt:
                start_dt = start_limit_dt

            st = int(start_dt.timestamp())
            et = int(end_dt.timestamp())
            print(f"⏳ Fetching {start_dt} → {end_dt} (UTC)")
            resp = self.get_tpseries(exch, token, interval, st, et)

            if isinstance(resp, dict):
                print(f"⚠️ TPSeries chunk returned dict: {resp.get('emsg') or resp.get('stat')}")
                end_dt = start_dt - timedelta(seconds=1)
                time.sleep(0.25)
                continue

            if not isinstance(resp, list) or len(resp) == 0:
                print("⚠️ Empty chunk. Moving back…")
                end_dt = start_dt - timedelta(seconds=1)
                time.sleep(0.25)
                continue

            df_chunk = pd.DataFrame(resp)
            all_chunks.append(df_chunk)
            end_dt = start_dt - timedelta(seconds=1)
            time.sleep(0.25)

        if not all_chunks:
            return pd.DataFrame()

        df = pd.concat(all_chunks, ignore_index=True)

        if "time" in df.columns:
            df.drop_duplicates(subset=["time"], inplace=True)
            df.sort_values(by="time", inplace=True)

        rename_map = {
            "time": "datetime",
            "into": "open",
            "inth": "high",
            "intl": "low",
            "intc": "close",
            "intvwap": "vwap",
            "intv": "volume",
            "intol": "open_interest_lot",
            "oi": "open_interest"
        }
        df.rename(columns=rename_map, inplace=True)

        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce", dayfirst=True)
            df = df.dropna(subset=["datetime"])

        df.sort_values("datetime", inplace=True)
        return df.reset_index(drop=True)

    def fetch_tpseries_for_watchlist(self, wlname, interval="5"):
        results = []
        MAX_CALLS_PER_MIN = 20
        call_count = 0

        symbols = self.get_watchlist(wlname)
        if not symbols or "values" not in symbols:
            print("❌ No symbols found in watchlist.")
            return []

        for idx, sym in enumerate(symbols["values"]):
            exch = sym.get("exch", "").strip()
            token = str(sym.get("token", "")).strip()
            symbol = sym.get("tsym", "").strip()

            if not token.isdigit():
                print(f"⚠️ Skipping {symbol}: Invalid token")
                continue

            try:
                print(f"\n📦 {idx+1}. {symbol} → {exch}|{token}")
                df = self.fetch_full_tpseries(exch, token, interval)
                if not df.empty:
                    print(f"✅ {symbol}: {len(df)} candles fetched.")
                    results.append({"symbol": symbol, "data": df})
                else:
                    print(f"⚠️ {symbol}: No data fetched.")
            except Exception as e:
                print(f"❌ {symbol}: Exception: {e}")

            call_count += 1
            if call_count >= MAX_CALLS_PER_MIN:
                print("⚠️ TPSeries limit reached. Skipping remaining.")
                break

        return results
        
    def normalize_response(self, resp):
        """
        Normalize ProStocks API response → always return a flat list of dicts.
        Prevents nested list-of-lists problem.
        """
        if resp is None:
            return []

        if isinstance(resp, str):
            try:
                resp = json.loads(resp)
            except:
                return []

        if isinstance(resp, dict):
            if "data" in resp and isinstance(resp["data"], list):
                return resp["data"]
            elif resp.get("stat") == "Ok":
                keys = set(resp.keys()) - {"stat"}
                return [resp] if keys else []
            else:
                return []

        if isinstance(resp, list):
            # ✅ If already list of dicts → return as-is
            if all(isinstance(i, dict) for i in resp):
                return resp
            # Otherwise flatten
            flat = []
            for item in resp:
                if isinstance(item, list):
                    flat.extend(item)
                elif isinstance(item, dict):
                    flat.append(item)
            return flat

        return []    
  
    
    def place_order(self, buy_or_sell, product_type, exchange, tradingsymbol,
                    quantity, discloseqty=0, price_type="MKT", price=None, trigger_price=None,
                    book_profit=None, book_loss=None, trail_price=None,
                    retention='DAY', remarks=''):
        """
        Place order (Normal / Bracket / SL) with support for Trailing Stop
        """
        url = f"{self.base_url}/PlaceOrder"
        order_data = {
            "uid": self.userid,
            "actid": self.userid,
            "exch": exchange,
            "tsym": tradingsymbol,
            "qty": str(quantity),
            "dscqty": str(discloseqty),
            "prd": product_type,
            "trantype": buy_or_sell,
            "prctyp": price_type,
            "ret": retention,
            "ordersource": "WEB",
            "remarks": remarks
        }

        # --- Price logic ---
        if price_type.upper() == "MKT":
            order_data["prc"] = "0"
        elif price is not None:
            order_data["prc"] = str(price)
        else:
            order_data["prc"] = "0"

        if trigger_price is not None:
            order_data["trgprc"] = str(trigger_price)

        # --- BO-specific fields ---
        if product_type == "B":
            if book_profit is not None:
                order_data["bpprc"] = str(book_profit)
            if book_loss is not None:
                order_data["blprc"] = str(book_loss)
            if trail_price is not None and float(trail_price) > 0:
                order_data["trailprc"] = str(trail_price)
            else:
                print("ℹ️ No trailing price applied (trail_price=None or 0).")

        print("📦 Order Payload:", order_data)

        # --- API request ---
        jdata_str = json.dumps(order_data, separators=(",", ":"))
        payload = f"jData={jdata_str}&jKey={self.session_token}"

        try:
            response = self.session.post(
                url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10
            )

            print("📨 Raw Response Text:", response.text)

            try:
                data = response.json()
            except Exception:
                return [{"stat": "Exception", "emsg": f"Invalid JSON: {response.text[:200]}"}]

            data = self.normalize_response(data)

            # Auto-refresh order/trade books if success
            if data and isinstance(data, list) and data[0].get("stat") == "Ok":
                self._order_book = self.order_book()
                self._trade_book = self.trade_book()

            return data

        except requests.exceptions.RequestException as e:
            print("❌ Place order exception:", e)
            return [{"stat": "Not_Ok", "emsg": str(e)}]
                 
    
    def modify_order(self, norenordno, tsym, blprc=None, bpprc=None, trgprc=None, qty=None, prc=None, prctyp=None, ret="DAY"):
        """
        Modify an existing order in ProStocks.
        blprc : stop-loss
        bpprc : target / book profit
        trgprc: trigger price for SL-MKT / SL-LMT
        qty   : modified quantity
        prc   : modified price
        prctyp: LMT / MKT / SL-MKT / SL-LMT
        """
        if not getattr(self, "jKey", None):
            raise ValueError("❌ Not logged in / jKey missing")
    
        jdata = {
            "norenordno": str(norenordno),
            "tsym": tsym,
            "blprc": blprc,
            "bpprc": bpprc,
            "trgprc": trgprc,
            "qty": qty,
            "prc": prc,
            "prctyp": prctyp,
            "ret": ret,
            "uid": self.user_id  # user id from login
        }
    
        # Remove None values
        jdata = {k: v for k, v in jdata.items() if v is not None}
    
        payload = {
            "jData": json.dumps(jdata),
            "jKey": self.jKey
        }
    
        url = f"{self.base_url}/ModifyOrder"
    
        try:
            resp = self.session.post(url, data=payload, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            data = self.normalize_response(data)   # ✅ cleanup
        
            # ✅ Refresh order/trade books only if order modified successfully
            if data and isinstance(data, list) and data[0].get("stat") == "Ok":
                self._order_book = self.order_book()
                self._trade_book = self.trade_book()
        
            return data
        except Exception as e:
            print(f"❌ ModifyOrder API failed: {e}")
            return [{"stat": "Exception", "emsg": str(e)}]   # ✅ wrapped in list

    def exit_bracket_order(self, norenordno: str, product_type: str = "B"):
        """
        Exit a Cover or Bracket order via /ExitSNOOrder.
    
        Args:
            norenordno: Noren order number to exit.
            product_type: 'B' for Bracket, 'H' for Cover.
        Returns:
            list[dict]: Normalized API response.
        """
        if not self.is_logged_in():
            return [{"stat": "Not_Ok", "emsg": "❌ Not logged in or session expired"}]

        url = f"{self.base_url}/ExitSNOOrder"

        jdata = {
            "uid": self.userid,
            "prd": product_type,
            "norenordno": str(norenordno)
        }

        payload = f"jData={json.dumps(jdata)}&jKey={self.session_token}"

        try:
            resp = self.session.post(
                url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=5
            )

            print("📨 ExitSNOOrder Response:", resp.text[:400])

            try:
                data = resp.json()
            except Exception:
                return [{"stat": "Exception", "emsg": f"Invalid JSON: {resp.text[:200]}"}]

            return self.normalize_response(data)

        except requests.exceptions.RequestException as e:
            print("❌ ExitSNOOrder failed:", e)
            return [{"stat": "Exception", "emsg": str(e)}]

            
    # prostocks_connector.py ke andar ProStocksAPI class me add karein
    def is_logged_in(self):
        """Check if session key / jKey exists and is valid"""
        return hasattr(self, "session_token") and self.session_token is not None and len(self.session_token) > 0


    def order_book(self):
        url = f"{self.base_url}/OrderBook"
        jdata_str = json.dumps({
            "uid": self.userid,
            "actid": self.actid
        })
        payload = f"jData={jdata_str}&jKey={self.session_token}"
        try:
            resp = self.session.post(url, data=payload, headers=self.headers, timeout=10)
            print("📨 Order Book Response:", resp.text)
            data = resp.json()
            return self.normalize_response(data)   # ✅ cleanup
        except requests.exceptions.RequestException as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    def trade_book(self):
        url = f"{self.base_url}/TradeBook"
        jdata_str = json.dumps({
            "uid": self.userid,
            "actid": self.actid
        })
        payload = f"jData={jdata_str}&jKey={self.session_token}"
        try:
            resp = self.session.post(url, data=payload, headers=self.headers, timeout=10)
            print("📨 Trade Book Response:", resp.text)
            data = resp.json()
            return self.normalize_response(data)   # ✅ cleanup
        except requests.exceptions.RequestException as e:
            return {"stat": "Not_Ok", "emsg": str(e)}
   
  # ---------------- WebSocket helpers ----------------
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


    # inside ProStocksAPI class

    # store recent candles per symbol+interval in memory
    self.live_candles = {}  # key -> list of last N candles

    def start_candle_builder(self, intervals=[1,3,5,15,30,60], max_candles=500):
        """
        Start a background thread that consumes self.tick_queue and builds candles
        stored in self.live_candles keyed by 'EXCH|TOKEN|interval'.
        """
        import threading, time
        def builder():
            buffers = {}  # key -> list of ticks for current bucket
            while True:
                try:
                    tick = self.tick_queue.get()  # blocking
                    ts = int(tick.get("ft") or tick.get("time") or 0)
                    if ts == 0:
                    continue
                    price = float(tick.get("lp") or 0)
                    exch = tick.get("e") or tick.get("exch") or "NSE"
                    token = str(tick.get("tk") or tick.get("token") or "")
                    if not token:
                        continue

                    for m in intervals:
                        key = f"{exch}|{token}|{m}"
                        bucket = ts - (ts % (m * 60))
                        b = buffers.setdefault(key, {"bucket": bucket, "ticks": []})
                        if bucket != b["bucket"]:
                            # close previous bucket
                            if b["ticks"]:
                                o = float(b["ticks"][0]["lp"])
                                c = float(b["ticks"][-1]["lp"])
                                h = max(float(tk["lp"]) for tk in b["ticks"])
                                l = min(float(tk["lp"]) for tk in b["ticks"])
                                candle = {"time": b["bucket"], "open": o, "high": h, "low": l, "close": c, "volume": sum(int(tk.get("v") or 0) for tk in b["ticks"])}
                                lst = self.live_candles.setdefault(key, [])
                                lst.append(candle)
                                if len(lst) > max_candles:
                                    lst.pop(0)
                                # call hook if exists
                                if hasattr(self, "on_new_candle") and callable(self.on_new_candle):
                                    try:
                                        self.on_new_candle(f"{exch}|{token}", candle)
                                    except Exception:
                                        pass
                            # reset
                            buffers[key] = {"bucket": bucket, "ticks": []}
                        # append tick
                        buffers[key]["ticks"].append(tick)
                except Exception as e:
                    print("⚠️ candle_builder error:", e)
                    time.sleep(0.1)

        t = threading.Thread(target=builder, daemon=True)
        t.start()
        self._candle_builder_thread = t

    def get_latest_candles(self, exch, token, interval=1, limit=200):
        key = f"{exch}|{token}|{interval}"
        return list(self.live_candles.get(key, []))[-limit:]
    

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

                last_buckets = sorted(self.candles[key].keys())
                if last_buckets:
                    last_bucket = last_buckets[-1]
                    if bucket > last_bucket:
                        # ✅ Candle closed → trigger callback
                        closed_candle = self.candles[key][last_bucket]
                        df = pd.DataFrame(list(self.candles[key].values()))
                        df["datetime"] = pd.to_datetime(df["ts"], unit="s")
                        if hasattr(self, "on_new_candle") and self.on_new_candle:
                            try:
                                self.on_new_candle(f"{exch}|{token}", df)
                            except Exception as e:
                                print("❌ on_new_candle error:", e)

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

  
    # ---------------- Fetch Yesterday's Candles ----------------
    def fetch_yesterday_candles(self, exch, token, interval="5"):
        """
        ✅ Fetches yesterday's complete intraday candles (09:15–15:30 IST).
        Uses TPSeries API directly, normalized via self.normalize_response().
        Works even when called standalone or during batch screener.
        """
        import pytz, pandas as pd, time
        from datetime import datetime, timedelta, timezone

        try:
            ist = pytz.timezone("Asia/Kolkata")
            today_ist = datetime.now(ist).date()
            yesterday_ist = today_ist - timedelta(days=1)

            # --- Start & end times in IST ---
            start_ist = ist.localize(datetime.combine(yesterday_ist, datetime.min.time())) + timedelta(hours=9, minutes=15)
            end_ist   = ist.localize(datetime.combine(yesterday_ist, datetime.min.time())) + timedelta(hours=15, minutes=30)

            # --- Convert to UTC for TPSeries ---
            st = int(start_ist.astimezone(timezone.utc).timestamp())
            et = int(end_ist.astimezone(timezone.utc).timestamp())

            print(f"\n📅 Fetching YESTERDAY candles for {yesterday_ist} ({start_ist.time()}–{end_ist.time()} IST)")
            print(f"   → UTC Range: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(st))} to {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(et))}")

            # --- Payload same as get_tpseries ---
            payload = {
                "uid": self.userid,
                "exch": exch,
                "token": str(token),
                "st": str(st),
                "et": str(et),
                "intrv": str(interval)
            }

            url = f"{self.base_url}/TPSeries"
            resp = self._post_json(url, payload)

            # --- Normalize response (ensure list of dicts) ---
            resp_list = self.normalize_response(resp)
            if not resp_list:
                print(f"⚠️ No data received for {yesterday_ist} — {symbol if 'symbol' in locals() else token}")
                return pd.DataFrame()

            # --- Convert to DataFrame ---
            df = pd.DataFrame(resp_list)
            if df.empty:
                print("⚠️ Empty DataFrame after normalization.")
                return pd.DataFrame()

            # --- Rename columns ---
            rename_map = {
                "time": "datetime",
                "into": "open",
                "inth": "high",
                "intl": "low",
                "intc": "close",
                "intv": "volume"
            }
            df.rename(columns=rename_map, inplace=True)

            # --- Parse datetimes ---
            if "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce", dayfirst=True)
                df = df.dropna(subset=["datetime"])
                df["datetime"] = df["datetime"].dt.tz_localize("Asia/Kolkata", ambiguous="NaT", nonexistent="shift_forward")

            # --- Sort & clean ---
            df.sort_values("datetime", inplace=True)
            df.reset_index(drop=True, inplace=True)

            print(f"✅ Yesterday {len(df)} candles fetched successfully for {yesterday_ist}")
            return df

        except Exception as e:
            print(f"❌ fetch_yesterday_candles() failed: {e}")
            return pd.DataFrame()




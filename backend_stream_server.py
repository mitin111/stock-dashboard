# backend_stream_server.py
# backend_stream_server.py
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
import asyncio, json, logging, os
from prostocks_connector import ProStocksAPI

logging.basicConfig(level=logging.INFO)
app = FastAPI()

# ✅ Health check
@app.get("/")
@app.head("/")
def root():
    return {"status": "ok", "service": "backend-stream"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DO NOT LOGIN OR INIT WITHOUT USER SESSION ---
ps_api = None

@app.post("/init")
async def init_api(request: Request):
    global ps_api
    body = await request.json()

    # FULL OBJECT BUILD
    ps_api = ProStocksAPI(
        userid = body.get("userid"),
        password_plain = "",
        vc = body.get("vc"),
        api_key = body.get("api_key"),
        imei = body.get("imei"),
        base_url="https://starapi.prostocks.com/NorenWClientTP"
    )

    # ---- SESSION RESTORE ----
    ps_api.session_token = body.get("session_token")
    ps_api.jKey = body.get("jKey")

    # ProStocks API internal flags 
    ps_api.logged_in = True
    ps_api.is_logged_in = True
    ps_api.login_status = True
    ps_api.is_session_active = True
    ps_api._logged_in = True

    # account identifiers
    ps_api.uid = body.get("uid") or body.get("userid")
    ps_api.actid = body.get("actid") or body.get("userid")

    # token aliases
    ps_api.token = ps_api.jKey
    ps_api.susertoken = ps_api.jKey
    ps_api.auth = ps_api.jKey

    # restore headers from frontend
    incoming_headers = body.get("headers")
    if incoming_headers:
        ps_api.headers = incoming_headers
    else:
        ps_api.headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": ps_api.jKey
        }

    ps_api.ws_url = "wss://starapi.prostocks.com/NorenWSTP/"
    ps_api.is_ws_connected = False

    logging.info("✅ FULL LOGIN CLONED INTO BACKEND")
    return {"stat": "Ok", "msg": "Backend fully synced"}


clients = set()

async def broadcast(msg: str):
    dead = []
    for ws in list(clients):
        try:
            await ws.send_text(msg)
        except:
            dead.append(ws)
    for d in dead:
        clients.discard(d)

@app.on_event("startup")
async def startup_event():
    logging.info("Backend stream server ready ✅")


# ✅ MAIN LIVE WS FEED PIPE (FrontEnd → Backend)
# Store server event loop
event_loop = asyncio.get_event_loop()

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):

    global ps_api
    if ps_api is None or ps_api.session_token is None:
        await websocket.accept()
        await websocket.send_text(json.dumps({"error": "Session not initialized — login first"}))
        await websocket.close()
        return

    await websocket.accept()
    clients.add(websocket)
    logging.info(f"Client connected (total={len(clients)})")

    def on_tick(tick):
        try:
            token = tick.get("tk") or tick.get("token")
            price = tick.get("lp") or tick.get("ltp")
            ts = tick.get("ft") or tick.get("time")

            if not (token and price and ts):
                return

            payload = json.dumps({
                "tk": str(token),
                "lp": float(price),
                "ft": int(float(ts))
            })

            # ✅ Broadcast from WS thread safely
            asyncio.run_coroutine_threadsafe(broadcast(payload), event_loop)

        except Exception as e:
            logging.warning(f"on_tick error: {e}")

    ps_api._on_tick = on_tick  # ✅ Correct callback binding

    try:
        while True:
            await websocket.receive_text()
    except:
        pass
    finally:
        clients.discard(websocket)
        logging.info(f"Client disconnected (total={len(clients)})")


# ✅ HTTP Subscribe (frontend will call this)
@app.post("/subscribe")
async def subscribe(request: Request):
    global ps_api

    # 🚫 HARD STOP: Backend not initialized
    if ps_api is None or getattr(ps_api, "session_token", None) is None:
        return {"stat": "error", "emsg": "Session not initialized — call /init first"}

    body = await request.json()
    tokens = body.get("tokens", [])

    if not tokens or not isinstance(tokens, list):
        return {"stat": "error", "emsg": "tokens must be a non-empty list"}

    try:
        # ✅ Start WebSocket only once
        if not getattr(ps_api, "is_ws_connected", False):
            ps_api.start_ticks(tokens)   # ✅ WS Connect + Login + Subscribe
            ps_api.is_ws_connected = True
            logging.info(f"✅ WebSocket Started with tokens: {tokens}")

        # ✅ If already running → just subscribe more
        else:
            ps_api.subscribe_tokens(tokens)
            logging.info(f"➕ Subscribed more tokens: {tokens}")

        return {"stat": "Ok", "subscribed": tokens}

    except Exception as e:
        logging.error(f"❌ Subscribe failed: {e}")
        return {"stat": "error", "emsg": str(e)}


# ✅ ADD THIS AT THE VERY END OF FILE (LAST LINES)
if __name__ == "__main__":
    import time
    print("✅ Backend Stream Worker Running (no webserver)...")
    while True:
        time.sleep(9999)

# =========================================================
# 🔥 ORDER API (HTML Panel → Backend → batch_screener.py)
# =========================================================
@app.post("/order_api")
async def order_api_handler(request: Request):
    global ps_api

    # 🚫 If backend not initialized
    if ps_api is None or ps_api.session_token is None:
        return {"status": "error", "msg": "Backend not initialized — call /init first"}

    body = await request.json()
    symbol = body.get("symbol")
    qty = int(body.get("qty", 0))
    side = body.get("side")  # BUY / SELL

    if not symbol or qty <= 0:
        return {"status": "error", "msg": "Invalid symbol or qty"}

    # 🔥 Run full strategy logic from batch_screener.py
    try:
        from batch_screener import run_strategy_request

        result = await asyncio.to_thread(
            run_strategy_request, ps_api, symbol, qty, side
        )
        return result

    except Exception as e:
        return {"status": "error", "msg": str(e)}

# =========================================================
# 🔥 AUTO TRADER BACKEND CONTROL API
# =========================================================

auto_trader_running = False
auto_trader_task = None


async def auto_trader_loop():
    """
    Main background loop → keeps processing batch_screener main()
    """
    import asyncio
    from batch_screener import main as batch_main

    global auto_trader_running

    logging.info("🚀 Auto Trader Loop Started")

    while auto_trader_running:
        try:
            # MAIN STRATEGY CALL
            await asyncio.to_thread(batch_main)
        except Exception as e:
            logging.error(f"❌ Auto Trader error: {e}")

        # wait between cycles
        await asyncio.sleep(3)

    logging.info("🛑 Auto Trader Loop Stopped")

@app.post("/start_auto")
async def start_auto_api():

    global auto_trader_running, auto_trader_task

    if ps_api is None or ps_api.session_token is None:
        return {"status": "error", "msg": "Backend not initialized — call /init first"}

    if auto_trader_running:
        return {"status": "already_running", "msg": "Auto Trader already running"}

    auto_trader_running = True
    auto_trader_task = asyncio.create_task(auto_trader_loop())

    logging.info("⚡ Auto Trader started")
    return {"status": "ok", "msg": "Auto Trader started"}

@app.post("/stop_auto")
async def stop_auto_api():

    global auto_trader_running, auto_trader_task

    if not auto_trader_running:
        return {"status": "not_running", "msg": "Auto Trader already stopped"}

    auto_trader_running = False

    if auto_trader_task:
        auto_trader_task.cancel()
        auto_trader_task = None

    logging.info("🛑 Auto Trader stopped")
    return {"status": "ok", "msg": "Auto Trader stopped"}

@app.get("/auto_status")
async def auto_status_api():
    return {
        "status": "running" if auto_trader_running else "stopped"
    }






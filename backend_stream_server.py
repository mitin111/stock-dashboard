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

    jKey = body.get("jKey")
    userid = body.get("userid")
    vc = body.get("vc")
    api_key = body.get("api_key")
    imei = body.get("imei")

    # ✅ Must keep base_url (LIVE)
    ps_api = ProStocksAPI(
        userid=userid,
        password_plain="",
        vc=vc,
        api_key=api_key,
        imei=imei,
        base_url="https://starapi.prostocks.com/NorenWClientTP"   # ✅ FIXED REQUIRED
    )

    ps_api.session_token = jKey
    ps_api.jKey = jKey

    ps_api.ws_url = "wss://starapi.prostocks.com/NorenWSTP/"  # ✅ LIVE WS
    ps_api.is_ws_connected = False

    logging.info("✅ Backend attached to existing Frontend session (NO LOGIN)")
    return {"stat": "Ok", "msg": "Backend synced successfully"}



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
@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):

    # ❌ Do NOT allow WS before /init sets session
    global ps_api
    if ps_api is None or ps_api.session_token is None:
        await websocket.accept()
        await websocket.send_text(json.dumps({"error": "Session not initialized — login first"}))
        await websocket.close()
        return

    await websocket.accept()
    clients.add(websocket)
    logging.info(f"Client connected (total={len(clients)})")

    # ✅ Attach tick handler
    def on_tick(tick):
        try:
            token = tick.get("tk") or tick.get("token")
            price = tick.get("lp") or tick.get("ltp")
            ts = tick.get("ft") or tick.get("time")
            if not (token and price and ts):
                return

            payload = json.dumps({"tk": str(token), "lp": float(price), "ft": int(float(ts))})
            asyncio.create_task(broadcast(payload))
        except Exception as e:
            logging.warning(f"on_tick error: {e}")

    ps_api._on_tick = on_tick  # ✅ _ws_on_message इसी को call करता है

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









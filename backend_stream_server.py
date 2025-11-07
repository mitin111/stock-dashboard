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

# --- Init API ---
base_url = os.getenv("PROSTOCKS_BASE_URL", "https://starapiuat.prostocks.com/NorenWClientTP")
try:
    ps_api = ProStocksAPI(base_url=base_url)
    ps_api.ws_url = "wss://starapi.prostocks.com/NorenWSTP/"
    ps_api.is_ws_connected = False     # ✅ IMPORTANT
    logging.info(f"✅ ProStocksAPI initialized with base_url={base_url}")
except Exception as e:
    ps_api = None
    logging.error(f"❌ API Init failed: {e}")

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
    await websocket.accept()
    clients.add(websocket)
    logging.info(f"Client connected (total={len(clients)})")

    # ✅ Attach tick handler (this runs every tick)
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

    # ✅ Register callback
    ps_api.on_tick = on_tick

    try:
        while True:
            msg = await websocket.receive_text()
            # (optional: you can support frontend → backend direct subscribe here)
    except:
        pass
    finally:
        clients.discard(websocket)
        logging.info(f"Client disconnected (total={len(clients)})")


# ✅ HTTP Subscribe (frontend will call this)
@app.post("/subscribe")
async def subscribe(request: Request):
    body = await request.json()
    tokens = body.get("tokens", [])

    if not tokens or not isinstance(tokens, list):
        return {"stat": "error", "emsg": "tokens must be a non-empty list"}

    try:
        if not ps_api.is_ws_connected:
            ps_api.connect_websocket(tokens)       # ✅ Correct call
            ps_api.is_ws_connected = True
            logging.info(f"✅ WS Started with tokens: {tokens}")
        else:
            ps_api.subscribe_tokens(tokens)
            logging.info(f"➕ Subscribed more tokens: {tokens}")

        return {"stat": "Ok", "subscribed": tokens}

    except Exception as e:
        logging.error(f"❌ Subscribe failed: {e}")
        return {"stat": "error", "emsg": str(e)}





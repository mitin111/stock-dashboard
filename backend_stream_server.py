# backend_stream_server.py
# backend_stream_server.py
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
import asyncio, json, logging
from prostocks_connector import ProStocksAPI

logging.basicConfig(level=logging.INFO)
app = FastAPI()

# ✅ ADD THIS FIX
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

import os

# --- Safe defaults for Render/UAT ---
base_url = os.getenv("PROSTOCKS_BASE_URL", "https://starapiuat.prostocks.com/NorenWClientTP")

try:
    ps_api = ProStocksAPI(base_url=base_url)
    ps_api.ws_url = "wss://starapi.prostocks.com/NorenWSTP/"
    logging.info(f"✅ ProStocksAPI initialized successfully with base_url={base_url}")
except Exception as e:
    ps_api = None
    logging.error(f"❌ Failed to initialize ProStocksAPI: {e}")

clients = set()


async def broadcast(msg: str):
    dead = []
    for ws in list(clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for d in dead:
        clients.discard(d)


@app.on_event("startup")
async def startup_event():
    logging.info("Backend stream server starting...")


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    logging.info("Client connected. total=%d", len(clients))

    def on_tick(tick):
        try:
            token = tick.get("tk") or tick.get("token") or tick.get("tsym") or tick.get("symbol")
            last_price = tick.get("lp") or tick.get("ltp") or tick.get("price")
            raw_ts = tick.get("ft") or tick.get("time") or tick.get("lts") or tick.get("ltt")
            if not (token and last_price and raw_ts):
                return

            ts = int(float(raw_ts))
            if ts > 1_000_000_000_000:
                ts //= 1000

            payload = json.dumps({"tk": str(token), "ft": ts, "lp": float(last_price)})
            asyncio.create_task(broadcast(payload))
        except Exception as e:
            logging.warning("on_tick broadcast error: %s", e)

    try:
        while True:
            msg = await websocket.receive_text()
            try:
                j = json.loads(msg)
                if j.get("action") == "subscribe" and isinstance(j.get("tokens"), list):
                    ps_api.subscribe_tokens(j["tokens"])
                    await websocket.send_text(json.dumps({
                        "type": "info",
                        "msg": "subscribed",
                        "tokens": j["tokens"]
                    }))
            except Exception:
                pass
    except Exception:
        pass
    finally:
        clients.discard(websocket)
        logging.info("Client disconnected. total=%d", len(clients))



import asyncio

@app.post("/subscribe")
async def subscribe(request: Request):
    body = await request.json()
    tokens = body.get("tokens", [])

    if not tokens or not isinstance(tokens, list):
        return {"stat": "error", "emsg": "tokens must be a non-empty list"}

    try:
        # ✅ If WebSocket not connected → start it with tokens
        if not ps_api.is_ws_connected:
            ps_api.connect_websocket(tokens)
            ps_api.is_ws_connected = True
            logging.info(f"✅ WebSocket started with tokens: {tokens}")
        else:
            # ✅ If WebSocket already running → subscribe more tokens
            ps_api.subscribe_tokens(tokens)
            logging.info(f"➕ Added subscription: {tokens}")

        return {"stat": "Ok", "subscribed": tokens}

    except Exception as e:
        logging.error(f"❌ Subscribe error: {e}")
        return {"stat": "error", "emsg": str(e)}







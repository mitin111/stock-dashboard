# backend_stream_server.py
# backend_stream_server.py
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
import asyncio, json, logging
from prostocks_connector import ProStocksAPI

logging.basicConfig(level=logging.INFO)
app = FastAPI()
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

# ✅ HTTP Subscribe Endpoint
@app.post("/subscribe")
async def subscribe(request: Request):
    """
    Subscribe symbols from Streamlit via HTTP POST API.
    Example POST body:
    {
        "tokens": ["NSE|2885", "NSE|11872"]
    }
    """
    try:
        body = await request.json()
    except Exception:
        return {"stat": "error", "emsg": "invalid JSON"}

    tokens = body.get("tokens", [])
    if not isinstance(tokens, list):
        return {"stat": "error", "emsg": "tokens must be a list"}

    try:
        ps_api.subscribe_tokens(tokens)
        logging.info(f"✅ Subscribed via /subscribe: {tokens}")
        return {"stat": "Ok", "subscribed": tokens}
    except Exception as e:
        logging.warning(f"❌ Subscribe error: {e}")
        return {"stat": "error", "emsg": str(e)}


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
            # Extract required fields safely
            token = tick.get("tk") or tick.get("token")
            last_price = tick.get("lp") or tick.get("ltp") or tick.get("price")
            tstamp = tick.get("ft") or tick.get("time")

            if not (token and last_price and tstamp):
                return

            payload = json.dumps({
                "tk": token,        # exch|token e.g. NSE|21614
                "ft": int(tstamp),  # epoch seconds
                "lp": float(last_price)  # last traded price
            })

            asyncio.create_task(broadcast(payload))

        except Exception as e:
            logging.warning("on_tick broadcast error: %s", e)

        try:
            ps_api.connect_websocket([], on_tick=on_tick)  # subscribe later via POST /subscribe
        except Exception as e:
            logging.warning("ps_api.connect_websocket failed: %s", e)

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




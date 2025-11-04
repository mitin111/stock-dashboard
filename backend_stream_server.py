# backend_stream_server.py
from fastapi import FastAPI, WebSocket
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

ps_api = ProStocksAPI()  # uses env or defaults from your .env
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
    # optional: ensure login before connecting WS
    logging.info("Backend stream server starting...")

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    logging.info("Client connected. total=%d", len(clients))

    # on_tick must be sync callback that schedules asyncio task
    def on_tick(tick):
        try:
            payload = json.dumps({"type": "tick", "tick": tick}, default=str)
            asyncio.create_task(broadcast(payload))
        except Exception as e:
            logging.warning("on_tick broadcast error: %s", e)

    # Start connection (non-blocking) — subscribe tokens after login
    # Provide a sensible default or read from query params later
    try:
        # Example: subscribe to an initial token list if desired
        # tokens = ["NSE|11872"]  # or keep empty and let UI ask backend to subscribe
        ps_api.connect_websocket([], on_tick=on_tick)  # keep WS open; subscriptions via REST later
    except Exception as e:
        logging.warning("ps_api.connect_websocket failed: %s", e)

    try:
        while True:
            # keep connection alive; client may send messages (e.g., subscribe/unsubscribe) later
            msg = await websocket.receive_text()
            # optional: handle client messages like {"action":"subscribe","tokens":["NSE|11872"]}
            try:
                j = json.loads(msg)
                if j.get("action") == "subscribe" and isinstance(j.get("tokens"), list):
                    ps_api.subscribe_tokens(j["tokens"])
                    await websocket.send_text(json.dumps({"type":"info","msg":"subscribed","tokens":j["tokens"]}))
            except Exception:
                pass
    except Exception:
        pass
    finally:
        clients.discard(websocket)
        logging.info("Client disconnected. total=%d", len(clients))

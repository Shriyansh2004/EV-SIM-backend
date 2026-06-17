from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api import chargers, commands, sessions, ws
from app.api.ws import setup_broadcast_listeners
from app.csms.csms_handler import csms_registry
from app.csms.ws_adapter import FastAPIWebSocketAdapter
from app.ocpp_log.logger import ocpp_logger
from app.virtual_charger.simulator import simulator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
  from app.db.database import close_db, init_db
  from app.csms.session_manager import session_manager
  from app.virtual_charger.charger_pool import charger_pool

  await init_db()
  await charger_pool.load_from_db()
  await session_manager.load_from_db()
  setup_broadcast_listeners()
  await simulator.start()
  logger.info("EV-SIM started")
  yield
  await simulator.stop()
  await close_db()


app = FastAPI(
  title="EV-SIM",
  description="EV-SIM — Virtual EV chargers with OCPP 2.0.1 CSMS integration",
  version="1.0.0",
  lifespan=lifespan,
)

app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)

app.include_router(chargers.router)
app.include_router(sessions.router)
app.include_router(commands.router)
app.include_router(ws.router)


@app.websocket("/ocpp/{charger_id}")
async def ocpp_websocket(websocket: WebSocket, charger_id: str) -> None:
  await websocket.accept(subprotocol="ocpp2.0.1")
  logger.info("OCPP connection from charger: %s", charger_id)
  adapter = FastAPIWebSocketAdapter(websocket)
  try:
    await csms_registry.connect(charger_id, adapter)
    task = csms_registry._tasks.get(charger_id)
    if task:
      await task
  except Exception as e:
    logger.error("OCPP connection error for %s: %s", charger_id, e)
  finally:
    csms_registry.disconnect(charger_id)
    logger.info("OCPP disconnected: %s", charger_id)


@app.get("/api/ocpp/messages")
async def get_ocpp_messages(charger_id: Optional[str] = None, limit: int = 100):
  return [m.model_dump() for m in ocpp_logger.get_messages(charger_id, limit)]


@app.get("/api/health")
async def health():
  from app.virtual_charger.charger_pool import charger_pool

  return {
    "status": "ok",
    "chargers": len(charger_pool.list_all()),
    "connected": len(csms_registry.list_connected()),
  }

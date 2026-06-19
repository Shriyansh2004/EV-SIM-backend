from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.csms.command_service import command_service
from app.csms.session_manager import session_manager
from app.models.schemas import Session, StartSessionRequest, StopSessionRequest
from app.virtual_charger.charger_pool import charger_pool

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[Session])
async def list_sessions() -> list[Session]:
  return session_manager.list_sessions()


@router.get("/{session_id}", response_model=Session)
async def get_session(session_id: str) -> Session:
  session = session_manager.get_session(session_id)
  if not session:
    raise HTTPException(status_code=404, detail="Session not found")
  return session


@router.post("/start")
async def start_session(body: StartSessionRequest) -> dict:
  client = charger_pool.get(body.charger_id)
  if not client:
    raise HTTPException(status_code=404, detail="Charger not found")
  if not client._ws:
    raise HTTPException(status_code=400, detail="Charger not connected to CSMS")

  ev_id = client.get_plugged_ev(body.connector_id)
  if not ev_id:
    raise HTTPException(
      status_code=400,
      detail=f"No EV plugged into connector {body.connector_id}. Plug an EV first.",
    )

  result = await command_service.remote_start(
    body.charger_id,
    body.connector_id,
    body.id_token,
  )
  if not result.get("success"):
    raise HTTPException(status_code=400, detail=result.get("error"))
  return result


@router.post("/stop")
async def stop_session(body: StopSessionRequest) -> dict:
  client = charger_pool.get(body.charger_id)
  if not client:
    raise HTTPException(status_code=404, detail="Charger not found")

  transaction_id = body.session_id
  if not transaction_id:
    session = session_manager.get_active_session(body.charger_id)
    if session:
      transaction_id = session.id
    elif client._transaction_id:
      transaction_id = client._transaction_id

  if not transaction_id:
    raise HTTPException(status_code=400, detail="No active session to stop")

  result = await command_service.remote_stop(body.charger_id, transaction_id)
  if not result.get("success"):
    raise HTTPException(status_code=400, detail=result.get("error"))
  return result

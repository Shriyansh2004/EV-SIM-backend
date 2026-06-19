from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import CreateEvRequest, PlugEvRequest, VirtualEv
from app.virtual_ev.ev_pool import ev_pool
from app.virtual_ev.presets import EV_PRESETS

router = APIRouter(prefix="/api/evs", tags=["evs"])


@router.get("", response_model=list[VirtualEv])
async def list_evs() -> list[VirtualEv]:
  return ev_pool.list_all()


@router.get("/presets")
async def list_presets() -> list[dict]:
  return [p.model_dump() for p in EV_PRESETS]


@router.post("", response_model=VirtualEv, status_code=201)
async def create_ev(body: CreateEvRequest) -> VirtualEv:
  try:
    return await ev_pool.create(body)
  except ValueError as e:
    raise HTTPException(status_code=409, detail=str(e))


@router.get("/{ev_id}", response_model=VirtualEv)
async def get_ev(ev_id: str) -> VirtualEv:
  client = ev_pool.get(ev_id)
  if not client:
    raise HTTPException(status_code=404, detail="EV not found")
  return client.to_schema()


@router.delete("/{ev_id}", status_code=204)
async def delete_ev(ev_id: str) -> None:
  try:
    removed = await ev_pool.remove(ev_id)
    if not removed:
      raise HTTPException(status_code=404, detail="EV not found")
  except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))


@router.post("/{ev_id}/plug", response_model=VirtualEv)
async def plug_ev(ev_id: str, body: PlugEvRequest) -> VirtualEv:
  try:
    return await ev_pool.plug(ev_id, body.charger_id, body.connector_id)
  except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))


@router.post("/{ev_id}/unplug", response_model=VirtualEv)
async def unplug_ev(ev_id: str) -> VirtualEv:
  try:
    return await ev_pool.unplug(ev_id)
  except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))


@router.post("/{ev_id}/start-charging")
async def start_ev_charging(ev_id: str) -> dict:
  from app.csms.command_service import command_service
  from app.virtual_charger.charger_pool import charger_pool

  client = ev_pool.get(ev_id)
  if not client:
    raise HTTPException(status_code=404, detail="EV not found")
  if not client.is_plugged():
    raise HTTPException(status_code=400, detail="EV is not plugged into a charger")
  if client.is_charging():
    raise HTTPException(status_code=400, detail="EV is already charging")

  charger_id = client.config.charger_id
  connector_id = client.config.connector_id or 1
  charger = charger_pool.get(charger_id or "")
  if not charger or not charger._ws:
    raise HTTPException(status_code=400, detail="Charger is not connected to CSMS")

  result = await command_service.remote_start(charger_id, connector_id, "DEMO-TOKEN")
  if not result.get("success"):
    raise HTTPException(status_code=400, detail=result.get("error"))
  return result


@router.post("/{ev_id}/stop-charging")
async def stop_ev_charging(ev_id: str) -> dict:
  from app.csms.command_service import command_service
  from app.csms.session_manager import session_manager

  client = ev_pool.get(ev_id)
  if not client:
    raise HTTPException(status_code=404, detail="EV not found")
  if not client.is_charging():
    raise HTTPException(status_code=400, detail="EV is not charging")

  charger_id = client.config.charger_id
  session_id = client.config.session_id
  if not session_id and charger_id:
    session = session_manager.get_active_session(charger_id)
    if session:
      session_id = session.id

  if not charger_id or not session_id:
    raise HTTPException(status_code=400, detail="No active charging session")

  result = await command_service.remote_stop(charger_id, session_id)
  if not result.get("success"):
    raise HTTPException(status_code=400, detail=result.get("error"))
  return result

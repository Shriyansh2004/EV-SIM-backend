from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.csms.command_service import command_service
from app.models.schemas import AvailabilityRequest, ResetRequest, UnlockRequest
from app.virtual_charger.charger_pool import charger_pool

router = APIRouter(prefix="/api/commands", tags=["commands"])


@router.post("/reset")
async def reset_charger(body: ResetRequest) -> dict:
  if not charger_pool.get(body.charger_id):
    raise HTTPException(status_code=404, detail="Charger not found")
  result = await command_service.reset(body.charger_id, body.reset_type)
  if not result.get("success"):
    raise HTTPException(status_code=400, detail=result.get("error"))
  return result


@router.post("/availability")
async def change_availability(body: AvailabilityRequest) -> dict:
  if not charger_pool.get(body.charger_id):
    raise HTTPException(status_code=404, detail="Charger not found")
  result = await command_service.change_availability(
    body.charger_id,
    body.connector_id,
    body.operational_status,
  )
  if not result.get("success"):
    raise HTTPException(status_code=400, detail=result.get("error"))
  return result


@router.post("/unlock")
async def unlock_connector(body: UnlockRequest) -> dict:
  if not charger_pool.get(body.charger_id):
    raise HTTPException(status_code=404, detail="Charger not found")
  result = await command_service.unlock_connector(body.charger_id, body.connector_id)
  if not result.get("success"):
    raise HTTPException(status_code=400, detail=result.get("error"))
  return result

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.csms.csms_handler import csms_registry
from app.models.schemas import CreateChargerRequest, VirtualCharger, ChargerConfig
from app.virtual_charger.charger_pool import charger_pool

router = APIRouter(prefix="/api/chargers", tags=["chargers"])


@router.get("", response_model=list[VirtualCharger])
async def list_chargers() -> list[VirtualCharger]:
  return charger_pool.list_all()


@router.post("", response_model=VirtualCharger, status_code=201)
async def create_charger(body: CreateChargerRequest) -> VirtualCharger:
  try:
    config = ChargerConfig(
      id=body.id,
      max_power_kw=body.max_power_kw,
      connector_count=body.connector_count,
    )
    return await charger_pool.create(config)
  except ValueError as e:
    raise HTTPException(status_code=409, detail=str(e))


@router.get("/{charger_id}", response_model=VirtualCharger)
async def get_charger(charger_id: str) -> VirtualCharger:
  client = charger_pool.get(charger_id)
  if not client:
    raise HTTPException(status_code=404, detail="Charger not found")
  return VirtualCharger(**client.to_dict())


@router.delete("/{charger_id}", status_code=204)
async def delete_charger(charger_id: str) -> None:
  removed = await charger_pool.remove(charger_id)
  if not removed:
    raise HTTPException(status_code=404, detail="Charger not found")
  csms_registry.disconnect(charger_id)


@router.post("/{charger_id}/connect", response_model=VirtualCharger)
async def connect_charger(charger_id: str) -> VirtualCharger:
  try:
    return await charger_pool.connect(charger_id)
  except ValueError as e:
    raise HTTPException(status_code=404, detail=str(e))
  except Exception as e:
    raise HTTPException(status_code=500, detail=f"Connection failed: {e}")


@router.post("/{charger_id}/disconnect", response_model=VirtualCharger)
async def disconnect_charger(charger_id: str) -> VirtualCharger:
  try:
    return await charger_pool.disconnect(charger_id)
  except ValueError as e:
    raise HTTPException(status_code=404, detail=str(e))


@router.post("/{charger_id}/fault")
async def inject_fault(charger_id: str, fault_type: str = "connector_error") -> dict:
  client = charger_pool.get(charger_id)
  if not client:
    raise HTTPException(status_code=404, detail="Charger not found")
  await charger_pool.inject_fault(charger_id, fault_type)
  return {"success": True, "fault_type": fault_type}

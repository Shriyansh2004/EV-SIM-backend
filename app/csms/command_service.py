from __future__ import annotations

from typing import Any, Optional

from app.csms.csms_handler import csms_registry


class CommandService:
  async def remote_start(
    self,
    charger_id: str,
    connector_id: int = 1,
    id_token: str = "DEMO-TOKEN",
  ) -> dict[str, Any]:
    cp = csms_registry.get(charger_id)
    if not cp:
      return {"success": False, "error": "Charger not connected to CSMS"}
    response = await cp.send_request_start(connector_id, id_token)
    return {"success": True, "status": str(response.status)}

  async def remote_stop(self, charger_id: str, transaction_id: str) -> dict[str, Any]:
    cp = csms_registry.get(charger_id)
    if not cp:
      return {"success": False, "error": "Charger not connected to CSMS"}
    response = await cp.send_request_stop(transaction_id)
    return {"success": True, "status": str(response.status)}

  async def reset(self, charger_id: str, reset_type: str = "Immediate") -> dict[str, Any]:
    cp = csms_registry.get(charger_id)
    if not cp:
      return {"success": False, "error": "Charger not connected to CSMS"}
    response = await cp.send_reset(reset_type)
    return {"success": True, "status": str(response.status)}

  async def change_availability(
    self,
    charger_id: str,
    connector_id: int,
    operational_status: str,
  ) -> dict[str, Any]:
    cp = csms_registry.get(charger_id)
    if not cp:
      return {"success": False, "error": "Charger not connected to CSMS"}
    response = await cp.send_change_availability(connector_id, operational_status)
    return {"success": True, "status": str(response.status)}

  async def unlock_connector(self, charger_id: str, connector_id: int = 1) -> dict[str, Any]:
    cp = csms_registry.get(charger_id)
    if not cp:
      return {"success": False, "error": "Charger not connected to CSMS"}
    response = await cp.send_unlock_connector(connector_id)
    return {"success": True, "status": str(response.status)}


command_service = CommandService()

from __future__ import annotations

from typing import Any, Callable, Optional

from app.db.repository import charger_repository
from app.models.schemas import ChargerConfig, ChargerStatus, VirtualCharger
from app.virtual_charger.charger import VirtualChargerClient


class ChargerPool:
  def __init__(self) -> None:
    self._chargers: dict[str, VirtualChargerClient] = {}
    self._csms_url = "ws://localhost:8000/ocpp"
    self._listeners: list[Callable[[str, dict[str, Any]], None]] = []

  def set_csms_url(self, url: str) -> None:
    self._csms_url = url

  def subscribe(self, listener: Callable[[str, dict[str, Any]], None]) -> None:
    self._listeners.append(listener)

  def _broadcast(self, event_type: str, data: dict[str, Any]) -> None:
    for listener in self._listeners:
      listener(event_type, data)

  async def load_from_db(self) -> None:
    records = await charger_repository.list_all()
    for record in records:
      if record.id in self._chargers:
        continue
      config = ChargerConfig(
        id=record.id,
        max_power_kw=record.max_power_kw,
        connector_count=record.connector_count,
      )
      client = VirtualChargerClient(
        config,
        on_update=lambda et, d: self._broadcast(et, d),
      )
      client.status = ChargerStatus(record.status)
      if record.connector_statuses:
        client._connector_statuses = [
          ChargerStatus(s) for s in record.connector_statuses
        ]
      self._chargers[record.id] = client

  async def create(self, config: ChargerConfig) -> VirtualCharger:
    if config.id in self._chargers:
      raise ValueError(f"Charger {config.id} already exists")

    await charger_repository.create(config)

    client = VirtualChargerClient(
      config,
      on_update=lambda et, d: self._broadcast(et, d),
    )
    self._chargers[config.id] = client
    return VirtualCharger(**client.to_dict())

  def get(self, charger_id: str) -> Optional[VirtualChargerClient]:
    return self._chargers.get(charger_id)

  def list_all(self) -> list[VirtualCharger]:
    return [VirtualCharger(**c.to_dict()) for c in self._chargers.values()]

  async def connect(self, charger_id: str) -> VirtualCharger:
    client = self._chargers.get(charger_id)
    if not client:
      raise ValueError(f"Charger {charger_id} not found")
    await client.connect_to_csms(self._csms_url)
    return VirtualCharger(**client.to_dict())

  async def disconnect(self, charger_id: str) -> VirtualCharger:
    client = self._chargers.get(charger_id)
    if not client:
      raise ValueError(f"Charger {charger_id} not found")
    await client.disconnect_from_csms()
    return VirtualCharger(**client.to_dict())

  async def remove(self, charger_id: str) -> bool:
    client = self._chargers.pop(charger_id, None)
    if client:
      if client._ws:
        await client.disconnect_from_csms()
      await charger_repository.delete(charger_id)
      from app.csms.session_manager import session_manager

      session_manager.remove_sessions_for_charger(charger_id)
      return True
    return False

  async def inject_fault(self, charger_id: str, fault_type: str) -> None:
    client = self._chargers.get(charger_id)
    if client:
      await client.inject_fault(fault_type)


charger_pool = ChargerPool()

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from app.db.repository import ev_repository
from app.models.schemas import CreateEvRequest, EvStatus, EvType, VirtualEv
from app.virtual_ev.ev import VirtualEvClient


class EvPool:
  def __init__(self) -> None:
    self._evs: dict[str, VirtualEvClient] = {}
    self._listeners: list[Callable[[str, dict[str, Any]], None]] = []

  def subscribe(self, listener: Callable[[str, dict[str, Any]], None]) -> None:
    self._listeners.append(listener)

  def _broadcast(self, event_type: str, data: dict[str, Any]) -> None:
    for listener in self._listeners:
      listener(event_type, data)

  async def load_from_db(self) -> None:
    records = await ev_repository.list_all()
    for record in records:
      if record.id in self._evs:
        continue
      ev = VirtualEv(
        id=record.id,
        name=record.name,
        vendor=record.vendor,
        model=record.model,
        ev_type=EvType(record.ev_type),
        battery_capacity_kwh=record.battery_capacity_kwh,
        max_charge_power_kw=record.max_charge_power_kw,
        max_ac_charge_power_kw=record.max_ac_charge_power_kw,
        max_dc_charge_power_kw=record.max_dc_charge_power_kw,
        soc_percent=record.soc_percent,
        target_soc_percent=record.target_soc_percent,
        status=EvStatus(record.status),
        charger_id=record.charger_id,
        connector_id=record.connector_id,
        session_id=record.session_id,
        energy_charged_kwh=record.energy_charged_kwh,
        current_power_kw=record.current_power_kw,
        voltage_v=record.voltage_v,
        current_a=record.current_a,
        created_at=record.created_at,
      )
      self._evs[record.id] = VirtualEvClient(ev)

    from app.virtual_charger.charger_pool import charger_pool

    for client in self._evs.values():
      if client.config.charger_id and client.config.connector_id:
        charger = charger_pool.get(client.config.charger_id)
        if charger:
          charger.plug_ev(client.config.connector_id, client.ev_id)

  async def create(self, request: CreateEvRequest) -> VirtualEv:
    if request.id in self._evs:
      raise ValueError(f"EV {request.id} already exists")

    max_charge = max(request.max_ac_charge_power_kw, request.max_dc_charge_power_kw)
    ev = VirtualEv(
      id=request.id,
      name=request.name or f"{request.vendor} {request.model}",
      vendor=request.vendor,
      model=request.model,
      ev_type=request.ev_type,
      battery_capacity_kwh=request.battery_capacity_kwh,
      max_charge_power_kw=max_charge,
      max_ac_charge_power_kw=request.max_ac_charge_power_kw,
      max_dc_charge_power_kw=request.max_dc_charge_power_kw,
      soc_percent=request.soc_percent,
      target_soc_percent=request.target_soc_percent,
      status=EvStatus.IDLE,
      created_at=datetime.utcnow().isoformat() + "Z",
    )
    await ev_repository.create(ev)
    client = VirtualEvClient(ev)
    self._evs[request.id] = client
    self._broadcast("ev_created", client.to_dict())
    return client.to_schema()

  def get(self, ev_id: str) -> Optional[VirtualEvClient]:
    return self._evs.get(ev_id)

  def list_all(self) -> list[VirtualEv]:
    return [c.to_schema() for c in self._evs.values()]

  def get_by_connector(self, charger_id: str, connector_id: int) -> Optional[VirtualEvClient]:
    for client in self._evs.values():
      if (
        client.config.charger_id == charger_id
        and client.config.connector_id == connector_id
      ):
        return client
    return None

  async def plug(self, ev_id: str, charger_id: str, connector_id: int) -> VirtualEv:
    client = self._evs.get(ev_id)
    if not client:
      raise ValueError(f"EV {ev_id} not found")
    if client.is_plugged():
      raise ValueError(f"EV {ev_id} is already plugged into {client.config.charger_id}")
    if client.is_charging():
      raise ValueError(f"EV {ev_id} is currently charging")

    existing = self.get_by_connector(charger_id, connector_id)
    if existing:
      raise ValueError(
        f"Connector {connector_id} on {charger_id} is already occupied by EV {existing.ev_id}"
      )

    from app.virtual_charger.charger_pool import charger_pool

    charger = charger_pool.get(charger_id)
    if not charger:
      raise ValueError(f"Charger {charger_id} not found")
    if connector_id < 1 or connector_id > charger.config.connector_count:
      raise ValueError(f"Invalid connector {connector_id} for charger {charger_id}")

    connector_status = charger._connector_statuses[connector_id - 1]
    from app.models.schemas import ChargerStatus

    if connector_status not in (ChargerStatus.AVAILABLE, ChargerStatus.PREPARING):
      raise ValueError(f"Connector {connector_id} is not available (status: {connector_status.value})")

    client.plug(charger_id, connector_id)
    charger.plug_ev(connector_id, ev_id)
    await ev_repository.update(client.to_schema())
    self._broadcast("ev_plugged", client.to_dict())
    return client.to_schema()

  async def unplug(self, ev_id: str) -> VirtualEv:
    client = self._evs.get(ev_id)
    if not client:
      raise ValueError(f"EV {ev_id} not found")
    if client.is_charging():
      raise ValueError(f"EV {ev_id} is charging — stop charging before unplugging")

    charger_id = client.config.charger_id
    connector_id = client.config.connector_id
    client.unplug()

    if charger_id and connector_id:
      from app.virtual_charger.charger_pool import charger_pool

      charger = charger_pool.get(charger_id)
      if charger:
        charger.unplug_ev(connector_id)

    await ev_repository.update(client.to_schema())
    self._broadcast("ev_unplugged", client.to_dict())
    return client.to_schema()

  async def start_charging(self, ev_id: str, session_id: str) -> VirtualEv:
    client = self._evs.get(ev_id)
    if not client:
      raise ValueError(f"EV {ev_id} not found")
    if not client.is_plugged():
      raise ValueError(f"EV {ev_id} is not plugged into a charger")
    if client.config.soc_percent >= client.config.target_soc_percent:
      raise ValueError(f"EV {ev_id} has already reached target SoC")

    client.start_charging(session_id)
    await ev_repository.update(client.to_schema())
    self._broadcast("ev_charging_started", client.to_dict())
    return client.to_schema()

  async def stop_charging(self, ev_id: str) -> VirtualEv:
    client = self._evs.get(ev_id)
    if not client:
      raise ValueError(f"EV {ev_id} not found")

    client.stop_charging()
    await ev_repository.update(client.to_schema())
    self._broadcast("ev_charging_stopped", client.to_dict())
    return client.to_schema()

  async def tick_all(self) -> None:
    from app.virtual_charger.charger_pool import charger_pool

    for client in self._evs.values():
      if not client.is_charging():
        continue

      charger = charger_pool.get(client.config.charger_id or "")
      charger_max = charger.config.max_power_kw if charger else 22.0
      telemetry = client.tick(charger_max, delta_s=1.0)
      await ev_repository.update(client.to_schema())
      self._broadcast("ev_update", {**client.to_dict(), **telemetry})

      if telemetry.get("charging_complete") and charger and client.config.session_id:
        from app.csms.command_service import command_service

        await command_service.remote_stop(
          client.config.charger_id or "",
          client.config.session_id,
        )

  async def remove(self, ev_id: str) -> bool:
    client = self._evs.pop(ev_id, None)
    if not client:
      return False
    if client.is_charging():
      raise ValueError(f"Cannot delete EV {ev_id} while charging")
    if client.is_plugged():
      await self.unplug(ev_id)
    await ev_repository.delete(ev_id)
    self._broadcast("ev_deleted", {"ev_id": ev_id})
    return True

  async def persist(self, ev_id: str) -> None:
    client = self._evs.get(ev_id)
    if client:
      await ev_repository.update(client.to_schema())


ev_pool = EvPool()

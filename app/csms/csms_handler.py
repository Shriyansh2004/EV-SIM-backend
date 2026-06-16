from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Callable, Optional

from ocpp.routing import on
from ocpp.v201 import ChargePoint as cp
from ocpp.v201 import call, call_result
from ocpp.v201.enums import (
  Action,
  AuthorizationStatusEnumType,
  ConnectorStatusEnumType,
  RegistrationStatusEnumType,
  RequestStartStopStatusEnumType,
)

from app.csms.session_manager import session_manager
from app.models.schemas import (
  ChargerStatus,
  MessageDirection,
  MessageType,
  MeterValue,
  SessionStatus,
)
from app.ocpp_log.logger import ocpp_logger

logger = logging.getLogger(__name__)

STATUS_MAP = {
  ConnectorStatusEnumType.available: ChargerStatus.AVAILABLE,
  ConnectorStatusEnumType.occupied: ChargerStatus.CHARGING,
  ConnectorStatusEnumType.reserved: ChargerStatus.RESERVED,
  ConnectorStatusEnumType.unavailable: ChargerStatus.UNAVAILABLE,
  ConnectorStatusEnumType.faulted: ChargerStatus.FAULTED,
}


class ConnectedChargePoint(cp):
  def __init__(
    self,
    charger_id: str,
    connection,
    on_update: Optional[Callable[[str, dict[str, Any]], None]] = None,
  ) -> None:
    super().__init__(charger_id, connection)
    self.charger_id = charger_id
    self.on_update = on_update
    self.heartbeat_interval = 30
    self._pending_calls: dict[str, asyncio.Future] = {}

  def _notify(self, event_type: str, data: dict[str, Any]) -> None:
    if self.on_update:
      self.on_update(event_type, data)

  def _log_in(self, action: str, payload: dict, correlation_id: Optional[str] = None) -> None:
    msg = ocpp_logger.log(
      self.charger_id,
      MessageDirection.CP_TO_CSMS,
      MessageType.REQUEST,
      action,
      payload,
      correlation_id,
    )
    self._notify("ocpp_message", msg.model_dump())

  def _log_out(
    self,
    action: str,
    payload: dict,
    correlation_id: Optional[str] = None,
    message_type: MessageType = MessageType.RESPONSE,
  ) -> None:
    msg = ocpp_logger.log(
      self.charger_id,
      MessageDirection.CSMS_TO_CP,
      message_type,
      action,
      payload,
      correlation_id,
    )
    self._notify("ocpp_message", msg.model_dump())

  @on(Action.boot_notification)
  async def on_boot_notification(self, charging_station, reason, **kwargs):
    payload = {"charging_station": charging_station, "reason": reason, **kwargs}
    self._log_in("BootNotification", payload)

    response = call_result.BootNotification(
      current_time=datetime.utcnow().isoformat() + "Z",
      interval=30,
      status=RegistrationStatusEnumType.accepted,
    )
    self._log_out("BootNotification", response.__dict__)
    self._notify("charger_connected", {"charger_id": self.charger_id, "status": "Accepted"})
    return response

  @on(Action.heartbeat)
  async def on_heartbeat(self, **kwargs):
    self._log_in("Heartbeat", kwargs)
    response = call_result.Heartbeat(current_time=datetime.utcnow().isoformat() + "Z")
    self._log_out("Heartbeat", response.__dict__)
    self._notify(
      "charger_update",
      {"charger_id": self.charger_id, "last_heartbeat": response.current_time},
    )
    return response

  @on(Action.status_notification)
  async def on_status_notification(
    self,
    timestamp,
    connector_status,
    evse_id,
    connector_id,
    **kwargs,
  ):
    payload = {
      "timestamp": timestamp,
      "connector_status": connector_status,
      "evse_id": evse_id,
      "connector_id": connector_id,
      **kwargs,
    }
    self._log_in("StatusNotification", payload)

    status = STATUS_MAP.get(connector_status, ChargerStatus.AVAILABLE)
    response = call_result.StatusNotification()
    self._log_out("StatusNotification", {})
    self._notify(
      "charger_update",
      {
        "charger_id": self.charger_id,
        "status": status.value,
        "connector_id": connector_id,
      },
    )
    return response

  @on(Action.authorize)
  async def on_authorize(self, id_token, **kwargs):
    payload = {"id_token": id_token, **kwargs}
    self._log_in("Authorize", payload)
    response = call_result.Authorize(
      id_token_info={"status": AuthorizationStatusEnumType.accepted}
    )
    self._log_out("Authorize", {"id_token_info": {"status": "Accepted"}})
    return response

  @on(Action.transaction_event)
  async def on_transaction_event(
    self,
    event_type,
    timestamp,
    trigger_reason,
    seq_no,
    transaction_info,
    **kwargs,
  ):
    payload = {
      "event_type": event_type,
      "timestamp": timestamp,
      "trigger_reason": trigger_reason,
      "seq_no": seq_no,
      "transaction_info": transaction_info,
      **kwargs,
    }
    self._log_in("TransactionEvent", payload)

    transaction_id = transaction_info.get("transaction_id") if isinstance(transaction_info, dict) else getattr(transaction_info, "transaction_id", None)

    if event_type == "Started":
      evse = kwargs.get("evse", {})
      connector_id = evse.get("connector_id", 1) if isinstance(evse, dict) else 1
      session = session_manager.create_session(
        self.charger_id,
        connector_id=connector_id,
        transaction_id=transaction_id,
      )
      self._notify("session_started", session.model_dump())

    elif event_type == "Updated":
      meter_values = kwargs.get("meter_value", [])
      session = session_manager.get_active_session(self.charger_id)
      if session and meter_values:
        mv = _parse_meter_values(meter_values)
        if mv:
          updated = session_manager.add_meter_value(session.id, mv)
          if updated:
            self._notify("session_updated", updated.model_dump())

    elif event_type == "Ended":
      session = session_manager.get_active_session(self.charger_id)
      if session:
        ended = session_manager.end_session(session.id, SessionStatus.COMPLETED)
        if ended:
          self._notify("session_ended", ended.model_dump())

    response = call_result.TransactionEvent()
    self._log_out("TransactionEvent", {})
    return response

  @on(Action.meter_values)
  async def on_meter_values(self, evse_id, meter_value, **kwargs):
    payload = {"evse_id": evse_id, "meter_value": meter_value, **kwargs}
    self._log_in("MeterValues", payload)
    session = session_manager.get_active_session(self.charger_id)
    if session:
      mv = _parse_meter_values(meter_value)
      if mv:
        updated = session_manager.add_meter_value(session.id, mv)
        if updated:
          self._notify("session_updated", updated.model_dump())
    response = call_result.MeterValues()
    self._log_out("MeterValues", {})
    return response

  async def send_request_start(self, connector_id: int = 1, id_token: str = "DEMO-TOKEN"):
    request = call.RequestStartTransaction(
      id_token={"id_token": id_token, "type": "Central"},
      remote_start_id=int(datetime.utcnow().timestamp()),
      evse_id=connector_id,
    )
    self._log_out(
      "RequestStartTransaction",
      {
        "id_token": {"id_token": id_token, "type": "Central"},
        "evse_id": connector_id,
      },
      message_type=MessageType.REQUEST,
    )
    response = await self.call(request)
    self._log_in(
      "RequestStartTransaction",
      {"status": str(response.status)},
    )
    return response

  async def send_request_stop(self, transaction_id: str):
    request = call.RequestStopTransaction(transaction_id=transaction_id)
    self._log_out(
      "RequestStopTransaction",
      {"transaction_id": transaction_id},
      message_type=MessageType.REQUEST,
    )
    response = await self.call(request)
    self._log_in("RequestStopTransaction", {"status": str(response.status)})
    return response

  async def send_reset(self, reset_type: str = "Immediate"):
    from ocpp.v201.enums import ResetEnumType

    rt = ResetEnumType.immediate if reset_type == "Immediate" else ResetEnumType.on_idle
    request = call.Reset(type=rt)
    self._log_out("Reset", {"type": reset_type}, message_type=MessageType.REQUEST)
    response = await self.call(request)
    self._log_in("Reset", {"status": str(response.status)})
    return response

  async def send_change_availability(self, connector_id: int, operational_status: str):
    from ocpp.v201.enums import OperationalStatusEnumType

    status = (
      OperationalStatusEnumType.operative
      if operational_status == "Operative"
      else OperationalStatusEnumType.inoperative
    )
    request = call.ChangeAvailability(operational_status=status, evse={"id": connector_id})
    self._log_out(
      "ChangeAvailability",
      {"operational_status": operational_status, "evse_id": connector_id},
      message_type=MessageType.REQUEST,
    )
    response = await self.call(request)
    self._log_in("ChangeAvailability", {"status": str(response.status)})
    return response

  async def send_unlock_connector(self, connector_id: int = 1):
    request = call.UnlockConnector(evse_id=1, connector_id=connector_id)
    self._log_out(
      "UnlockConnector",
      {"evse_id": 1, "connector_id": connector_id},
      message_type=MessageType.REQUEST,
    )
    response = await self.call(request)
    self._log_in("UnlockConnector", {"status": str(response.status)})
    return response


def _parse_meter_values(meter_values: list) -> Optional[MeterValue]:
  if not meter_values:
    return None
  latest = meter_values[-1] if isinstance(meter_values, list) else meter_values
  timestamp = latest.get("timestamp", datetime.utcnow().isoformat() + "Z") if isinstance(latest, dict) else datetime.utcnow().isoformat() + "Z"
  sampled = latest.get("sampled_value", []) if isinstance(latest, dict) else []

  power_kw = 0.0
  energy_kwh = 0.0
  soc_percent = None
  voltage_v = None
  current_a = None

  for sv in sampled:
    if not isinstance(sv, dict):
      continue
    measurand = sv.get("measurand", "")
    value = float(sv.get("value", 0))
    unit = sv.get("unit_of_measure", {})
    multiplier = float(unit.get("multiplier", 0)) if unit else 0
    actual = value * (10 ** multiplier) if multiplier else value

    if "Power.Active.Import" in measurand:
      power_kw = actual / 1000 if unit and unit.get("unit") == "W" else actual
    elif "Energy.Active.Import.Register" in measurand:
      energy_kwh = actual / 1000 if (not unit or unit.get("unit") in ("Wh", "varh")) else actual
    elif "SoC" in measurand:
      soc_percent = actual
    elif "Voltage" in measurand:
      voltage_v = actual
    elif "Current.Import" in measurand:
      current_a = actual

  return MeterValue(
    timestamp=timestamp,
    power_kw=power_kw,
    energy_kwh=energy_kwh,
    soc_percent=soc_percent,
    voltage_v=voltage_v,
    current_a=current_a,
  )


class CsmsRegistry:
  def __init__(self) -> None:
    self._connections: dict[str, ConnectedChargePoint] = {}
    self._tasks: dict[str, asyncio.Task] = {}
    self._listeners: list[Callable[[str, dict[str, Any]], None]] = []

  def subscribe(self, listener: Callable[[str, dict[str, Any]], None]) -> None:
    self._listeners.append(listener)

  def _broadcast(self, event_type: str, data: dict[str, Any]) -> None:
    for listener in self._listeners:
      listener(event_type, data)

  async def connect(self, charger_id: str, websocket) -> ConnectedChargePoint:
    cp_instance = ConnectedChargePoint(
      charger_id,
      websocket,
      on_update=lambda et, d: self._broadcast(et, d),
    )
    self._connections[charger_id] = cp_instance
    task = asyncio.create_task(cp_instance.start())
    self._tasks[charger_id] = task
    return cp_instance

  def disconnect(self, charger_id: str) -> None:
    task = self._tasks.pop(charger_id, None)
    if task:
      task.cancel()
    self._connections.pop(charger_id, None)

  def get(self, charger_id: str) -> Optional[ConnectedChargePoint]:
    return self._connections.get(charger_id)

  def is_connected(self, charger_id: str) -> bool:
    return charger_id in self._connections

  def list_connected(self) -> list[str]:
    return list(self._connections.keys())


csms_registry = CsmsRegistry()

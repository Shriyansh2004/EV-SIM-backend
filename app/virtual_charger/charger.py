from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Optional
from uuid import uuid4

from ocpp.routing import on
from ocpp.v201 import ChargePoint as cp
from ocpp.v201 import call
from ocpp.v201.enums import Action, ConnectorStatusEnumType

from app.models.schemas import ChargerConfig, ChargerStatus, MessageDirection, MessageType
from app.ocpp_log.logger import ocpp_logger

logger = logging.getLogger(__name__)


class VirtualChargerClient(cp):
  def __init__(
    self,
    config: ChargerConfig,
    on_update: Optional[Callable[[str, dict[str, Any]], None]] = None,
  ) -> None:
    self.config = config
    self.charger_id = config.id
    self.status = ChargerStatus.AVAILABLE
    self.on_update = on_update
    self._ws = None
    self._heartbeat_task: Optional[asyncio.Task] = None
    self._meter_task: Optional[asyncio.Task] = None
    self._heartbeat_interval = 30
    self._transaction_id: Optional[str] = None
    self._seq_no = 0
    self._energy_wh = 0.0
    self._soc = 20.0
    self._is_charging = False
    self._connector_statuses = [ChargerStatus.AVAILABLE] * config.connector_count
    self._plugged_evs: dict[int, Optional[str]] = {i + 1: None for i in range(config.connector_count)}
    self._active_connector: int = 1
    super().__init__(config.id, None)

  def plug_ev(self, connector_id: int, ev_id: str) -> None:
    self._plugged_evs[connector_id] = ev_id
    self._connector_statuses[connector_id - 1] = ChargerStatus.PREPARING

  def unplug_ev(self, connector_id: int) -> None:
    self._plugged_evs[connector_id] = None
    if not self._is_charging or self._active_connector != connector_id:
      self._connector_statuses[connector_id - 1] = ChargerStatus.AVAILABLE

  def get_plugged_ev(self, connector_id: int) -> Optional[str]:
    return self._plugged_evs.get(connector_id)

  def _get_ev_soc(self, connector_id: int) -> float:
    ev_id = self._plugged_evs.get(connector_id)
    if not ev_id:
      return 20.0
    from app.virtual_ev.ev_pool import ev_pool

    ev = ev_pool.get(ev_id)
    return ev.soc if ev else 20.0

  def _get_charge_power(self, connector_id: int) -> float:
    ev_id = self._plugged_evs.get(connector_id)
    if not ev_id:
      return 0.0
    from app.virtual_ev.ev_pool import ev_pool
    from app.virtual_ev.ev import compute_charge_power

    ev = ev_pool.get(ev_id)
    if not ev:
      return 0.0
    return compute_charge_power(
      ev.soc,
      ev.config.max_charge_power_kw,
      self.config.max_power_kw,
      ev.config.target_soc_percent,
    )

  def _notify(self, event_type: str, data: dict[str, Any]) -> None:
    if self.on_update:
      self.on_update(event_type, data)

  def _log_out(self, action: str, payload: dict, correlation_id: Optional[str] = None) -> None:
    msg = ocpp_logger.log(
      self.charger_id,
      MessageDirection.CP_TO_CSMS,
      MessageType.REQUEST,
      action,
      payload,
      correlation_id,
    )
    self._notify("ocpp_message", msg.model_dump())

  def _log_in(
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

  async def connect_to_csms(self, url: str) -> None:
    import websockets

    ws_url = f"{url}/{self.charger_id}"
    self._ws = await websockets.connect(
      ws_url,
      subprotocols=["ocpp2.0.1"],
    )
    self._connection = self._ws
    asyncio.create_task(self.start())
    await self._boot_sequence()

  async def disconnect_from_csms(self) -> None:
    if self._heartbeat_task:
      self._heartbeat_task.cancel()
    if self._meter_task:
      self._meter_task.cancel()
    if self._ws:
      await self._ws.close()
      self._ws = None
    self._notify("charger_disconnected", {"charger_id": self.charger_id})

  async def _boot_sequence(self) -> None:
    self._log_out(
      "BootNotification",
      {
        "reason": "PowerUp",
        "charging_station": {
          "model": "VirtualCharger",
          "vendor_name": "EV-SIM",
        },
      },
    )
    request = call.BootNotification(
      reason="PowerUp",
      charging_station={
        "model": "VirtualCharger",
        "vendor_name": "EV-SIM",
      },
    )
    response = await self.call(request)
    self._log_in("BootNotification", {"status": str(response.status), "interval": response.interval})
    self._heartbeat_interval = response.interval
    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    for i in range(self.config.connector_count):
      await self._send_status_notification(i + 1, ConnectorStatusEnumType.available)

  async def _heartbeat_loop(self) -> None:
    while self._ws:
      await asyncio.sleep(self._heartbeat_interval)
      try:
        self._log_out("Heartbeat", {})
        request = call.Heartbeat()
        response = await self.call(request)
        self._log_in("Heartbeat", {"current_time": response.current_time})
        self._notify(
          "charger_update",
          {"charger_id": self.charger_id, "last_heartbeat": response.current_time},
        )
      except Exception as e:
        logger.error("Heartbeat failed for %s: %s", self.charger_id, e)
        break

  async def _send_status_notification(self, connector_id: int, status: ConnectorStatusEnumType) -> None:
    payload = {
      "evse_id": 1,
      "connector_id": connector_id,
      "connector_status": str(status),
      "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    self._log_out("StatusNotification", payload)
    request = call.StatusNotification(
      timestamp=datetime.utcnow().isoformat() + "Z",
      connector_status=status,
      evse_id=1,
      connector_id=connector_id,
    )
    await self.call(request)
    self._log_in("StatusNotification", {})

  def _build_meter_value(self, connector_id: int = 1) -> dict:
    power_kw = self._get_charge_power(connector_id) if self._is_charging else 0
    power_w = power_kw * 1000
    soc = self._get_ev_soc(connector_id)
    return {
      "timestamp": datetime.utcnow().isoformat() + "Z",
      "sampled_value": [
        {
          "value": self._energy_wh,
          "measurand": "Energy.Active.Import.Register",
          "unit_of_measure": {"unit": "Wh"},
        },
        {
          "value": power_w,
          "measurand": "Power.Active.Import",
          "unit_of_measure": {"unit": "W"},
        },
        {
          "value": int(soc),
          "measurand": "SoC",
          "unit_of_measure": {"unit": "Percent"},
        },
        {
          "value": 400,
          "measurand": "Voltage",
          "unit_of_measure": {"unit": "V"},
        },
        {
          "value": power_w / 400 if power_w > 0 else 0,
          "measurand": "Current.Import",
          "unit_of_measure": {"unit": "A"},
        },
      ],
    }

  async def _meter_loop(self) -> None:
    while self._is_charging:
      await asyncio.sleep(5)
      connector_id = self._active_connector
      power_kw = self._get_charge_power(connector_id)
      self._energy_wh += power_kw * 1000 * (5 / 3600)
      self._soc = self._get_ev_soc(connector_id)

      meter_value = [self._build_meter_value(connector_id)]
      self._seq_no += 1

      self._log_out(
        "TransactionEvent",
        {
          "event_type": "Updated",
          "trigger_reason": "MeterValuePeriodic",
          "seq_no": self._seq_no,
          "transaction_info": {"transaction_id": self._transaction_id},
          "meter_value": meter_value,
        },
      )
      request = call.TransactionEvent(
        event_type="Updated",
        timestamp=datetime.utcnow().isoformat() + "Z",
        trigger_reason="MeterValuePeriodic",
        seq_no=self._seq_no,
        transaction_info={"transaction_id": self._transaction_id},
        meter_value=meter_value,
      )
      await self.call(request)
      self._log_in("TransactionEvent", {})

      self._notify(
        "charger_update",
        {
          "charger_id": self.charger_id,
          "status": ChargerStatus.CHARGING.value,
          "current_power_kw": power_kw,
          "energy_kwh": self._energy_wh / 1000,
        },
      )

  async def _start_transaction(self, connector_id: int = 1, id_token: str = "DEMO-TOKEN") -> None:
    ev_id = self._plugged_evs.get(connector_id)
    if not ev_id:
      logger.warning("Cannot start transaction on connector %s — no EV plugged in", connector_id)
      return

    self._transaction_id = str(uuid4())
    self._seq_no = 1
    self._energy_wh = 0.0
    self._is_charging = True
    self._active_connector = connector_id
    self.status = ChargerStatus.CHARGING
    self._connector_statuses[connector_id - 1] = ChargerStatus.CHARGING
    self._soc = self._get_ev_soc(connector_id)

    from app.virtual_ev.ev_pool import ev_pool

    await ev_pool.start_charging(ev_id, self._transaction_id)

    await self._send_status_notification(connector_id, ConnectorStatusEnumType.occupied)

    meter_value = [self._build_meter_value(connector_id)]
    self._log_out(
      "TransactionEvent",
      {
        "event_type": "Started",
        "trigger_reason": "Authorized",
        "seq_no": self._seq_no,
        "transaction_info": {"transaction_id": self._transaction_id},
        "id_token": {"id_token": id_token, "type": "Central"},
        "evse": {"id": 1, "connector_id": connector_id},
        "meter_value": meter_value,
      },
    )
    request = call.TransactionEvent(
      event_type="Started",
      timestamp=datetime.utcnow().isoformat() + "Z",
      trigger_reason="Authorized",
      seq_no=self._seq_no,
      transaction_info={"transaction_id": self._transaction_id, "charging_state": "Charging"},
      id_token={"id_token": id_token, "type": "Central"},
      evse={"id": 1, "connector_id": connector_id},
      meter_value=meter_value,
    )
    await self.call(request)
    self._log_in("TransactionEvent", {})
    self._meter_task = asyncio.create_task(self._meter_loop())

  async def _stop_transaction(self) -> None:
    if not self._transaction_id:
      return
    connector_id = self._active_connector
    ev_id = self._plugged_evs.get(connector_id)

    self._is_charging = False
    if self._meter_task:
      self._meter_task.cancel()
      self._meter_task = None

    if ev_id:
      from app.virtual_ev.ev_pool import ev_pool

      await ev_pool.stop_charging(ev_id)

    self._seq_no += 1
    self._log_out(
      "TransactionEvent",
      {
        "event_type": "Ended",
        "trigger_reason": "RemoteStop",
        "seq_no": self._seq_no,
        "transaction_info": {
          "transaction_id": self._transaction_id,
          "stopped_reason": "Remote",
        },
        "meter_value": [self._build_meter_value(connector_id)],
      },
    )
    request = call.TransactionEvent(
      event_type="Ended",
      timestamp=datetime.utcnow().isoformat() + "Z",
      trigger_reason="RemoteStop",
      seq_no=self._seq_no,
      transaction_info={
        "transaction_id": self._transaction_id,
        "stopped_reason": "Remote",
      },
      meter_value=[self._build_meter_value(connector_id)],
    )
    await self.call(request)
    self._log_in("TransactionEvent", {})

    if ev_id:
      await self._send_status_notification(connector_id, ConnectorStatusEnumType.occupied)
      self._connector_statuses[connector_id - 1] = ChargerStatus.PREPARING
    else:
      await self._send_status_notification(connector_id, ConnectorStatusEnumType.available)
      self._connector_statuses[connector_id - 1] = ChargerStatus.AVAILABLE
    self.status = ChargerStatus.AVAILABLE if not self._is_charging else ChargerStatus.CHARGING
    self._transaction_id = None

  @on(Action.request_start_transaction)
  async def on_request_start_transaction(self, id_token, remote_start_id, **kwargs):
    payload = {"id_token": id_token, "remote_start_id": remote_start_id, **kwargs}
    self._log_in("RequestStartTransaction", payload, message_type=MessageType.REQUEST)

    evse_id = kwargs.get("evse_id", 1)
    token = id_token.get("id_token", "DEMO-TOKEN") if isinstance(id_token, dict) else "DEMO-TOKEN"
    asyncio.create_task(self._start_transaction(evse_id, token))

    from ocpp.v201 import call_result
    from ocpp.v201.enums import RequestStartStopStatusEnumType

    response = call_result.RequestStartTransaction(status=RequestStartStopStatusEnumType.accepted)
    self._log_out("RequestStartTransaction", {"status": "Accepted"})
    return response

  @on(Action.request_stop_transaction)
  async def on_request_stop_transaction(self, transaction_id, **kwargs):
    payload = {"transaction_id": transaction_id, **kwargs}
    self._log_in("RequestStopTransaction", payload, message_type=MessageType.REQUEST)

    asyncio.create_task(self._stop_transaction())

    from ocpp.v201 import call_result
    from ocpp.v201.enums import RequestStartStopStatusEnumType

    response = call_result.RequestStopTransaction(status=RequestStartStopStatusEnumType.accepted)
    self._log_out("RequestStopTransaction", {"status": "Accepted"})
    return response

  @on(Action.reset)
  async def on_reset(self, type, **kwargs):
    self._log_in("Reset", {"type": str(type)}, message_type=MessageType.REQUEST)
    if self._is_charging:
      await self._stop_transaction()
    await self._boot_sequence()
    from ocpp.v201 import call_result
    from ocpp.v201.enums import ResetStatusEnumType

    response = call_result.Reset(status=ResetStatusEnumType.accepted)
    self._log_out("Reset", {"status": "Accepted"})
    return response

  @on(Action.change_availability)
  async def on_change_availability(self, operational_status, **kwargs):
    self._log_in(
      "ChangeAvailability",
      {"operational_status": str(operational_status), **kwargs},
      message_type=MessageType.REQUEST,
    )
    from ocpp.v201 import call_result
    from ocpp.v201.enums import ChangeAvailabilityStatusEnumType

    response = call_result.ChangeAvailability(status=ChangeAvailabilityStatusEnumType.accepted)
    self._log_out("ChangeAvailability", {"status": "Accepted"})
    return response

  @on(Action.unlock_connector)
  async def on_unlock_connector(self, evse_id, connector_id, **kwargs):
    self._log_in(
      "UnlockConnector",
      {"evse_id": evse_id, "connector_id": connector_id},
      message_type=MessageType.REQUEST,
    )
    from ocpp.v201 import call_result
    from ocpp.v201.enums import UnlockStatusEnumType

    response = call_result.UnlockConnector(status=UnlockStatusEnumType.unlocked)
    self._log_out("UnlockConnector", {"status": "Unlocked"})
    return response

  def to_dict(self) -> dict[str, Any]:
    session = None
    if self._is_charging and self._transaction_id:
      connector_id = self._active_connector
      session = {
        "id": self._transaction_id,
        "charger_id": self.charger_id,
        "connector_id": connector_id,
        "ev_id": self._plugged_evs.get(connector_id),
        "start_time": datetime.utcnow().isoformat() + "Z",
        "energy_kwh": self._energy_wh / 1000,
        "current_power_kw": self._get_charge_power(connector_id),
        "status": "active",
      }
    return {
      "id": self.charger_id,
      "status": self.status.value,
      "connector_count": self.config.connector_count,
      "max_power_kw": self.config.max_power_kw,
      "is_connected": self._ws is not None,
      "current_session": session,
      "connector_statuses": [s.value for s in self._connector_statuses],
      "plugged_evs": {str(k): v for k, v in self._plugged_evs.items()},
    }

  async def inject_fault(self, fault_type: str) -> None:
    if fault_type == "network_drop":
      await self.disconnect_from_csms()
    elif fault_type == "connector_error":
      self.status = ChargerStatus.FAULTED
      await self._send_status_notification(1, ConnectorStatusEnumType.faulted)
      self._notify("charger_update", {"charger_id": self.charger_id, "status": "Faulted"})
    elif fault_type == "power_loss" and self._is_charging:
      await self._stop_transaction()
      self.status = ChargerStatus.UNAVAILABLE
      await self._send_status_notification(1, ConnectorStatusEnumType.unavailable)

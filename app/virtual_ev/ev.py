from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.models.schemas import EvStatus, EvType, VirtualEv


def compute_charge_power(
  soc: float,
  ev_max_kw: float,
  charger_max_kw: float,
  target_soc: float = 100.0,
) -> float:
  """Realistic charging curve with taper above 70% SoC."""
  if soc >= target_soc or soc >= 100.0:
    return 0.0

  effective_max = min(ev_max_kw, charger_max_kw)

  if soc >= 95:
    return effective_max * 0.15
  if soc >= 90:
    return effective_max * 0.30
  if soc >= 80:
    return effective_max * 0.55
  if soc >= 70:
    return effective_max * 0.80
  return effective_max


class VirtualEvClient:
  """Simulates an electric vehicle battery and charging behaviour."""

  def __init__(self, config: VirtualEv) -> None:
    self.config = config
    self.ev_id = config.id
    self._session_energy_kwh = 0.0

  @property
  def soc(self) -> float:
    return self.config.soc_percent

  @property
  def status(self) -> EvStatus:
    return self.config.status

  def is_plugged(self) -> bool:
    return self.config.charger_id is not None

  def is_charging(self) -> bool:
    return self.config.status == EvStatus.CHARGING

  def plug(self, charger_id: str, connector_id: int) -> None:
    self.config.charger_id = charger_id
    self.config.connector_id = connector_id
    self.config.status = EvStatus.PLUGGED
    self.config.voltage_v = 0.0
    self.config.current_a = 0.0
    self.config.current_power_kw = 0.0

  def unplug(self) -> None:
    self.config.charger_id = None
    self.config.connector_id = None
    self.config.session_id = None
    self.config.status = EvStatus.IDLE
    self.config.current_power_kw = 0.0
    self.config.voltage_v = 0.0
    self.config.current_a = 0.0

  def start_charging(self, session_id: str) -> None:
    self.config.session_id = session_id
    self.config.status = EvStatus.CHARGING
    self._session_energy_kwh = 0.0

  def stop_charging(self) -> None:
    self.config.session_id = None
    self.config.current_power_kw = 0.0
    self.config.voltage_v = 0.0
    self.config.current_a = 0.0
    if self.is_plugged():
      self.config.status = EvStatus.PLUGGED
    else:
      self.config.status = EvStatus.IDLE

  def tick(self, charger_max_kw: float, delta_s: float = 1.0) -> dict[str, Any]:
    """Advance simulation by delta_s seconds. Returns telemetry dict."""
    if not self.is_charging():
      return self._telemetry()

    ev_max = self.config.max_charge_power_kw
    power_kw = compute_charge_power(
      self.config.soc_percent,
      ev_max,
      charger_max_kw,
      self.config.target_soc_percent,
    )

    if power_kw <= 0:
      self.config.status = EvStatus.FULL if self.config.soc_percent >= self.config.target_soc_percent else EvStatus.PLUGGED
      self.config.current_power_kw = 0.0
      self.config.voltage_v = 0.0
      self.config.current_a = 0.0
      return self._telemetry(charging_complete=True)

    energy_kwh = power_kw * (delta_s / 3600.0)
    soc_delta = (energy_kwh / self.config.battery_capacity_kwh) * 100.0
    self.config.soc_percent = min(100.0, self.config.soc_percent + soc_delta)
    self.config.energy_charged_kwh += energy_kwh
    self._session_energy_kwh += energy_kwh
    self.config.current_power_kw = power_kw
    self.config.voltage_v = 400.0
    self.config.current_a = (power_kw * 1000) / 400.0 if power_kw > 0 else 0.0

    if self.config.soc_percent >= self.config.target_soc_percent:
      self.config.status = EvStatus.FULL
      self.config.current_power_kw = 0.0
      return self._telemetry(charging_complete=True)

    return self._telemetry()

  def _telemetry(self, charging_complete: bool = False) -> dict[str, Any]:
    return {
      "ev_id": self.ev_id,
      "soc_percent": round(self.config.soc_percent, 2),
      "current_power_kw": round(self.config.current_power_kw, 3),
      "energy_charged_kwh": round(self.config.energy_charged_kwh, 4),
      "session_energy_kwh": round(self._session_energy_kwh, 4),
      "voltage_v": round(self.config.voltage_v, 1),
      "current_a": round(self.config.current_a, 2),
      "status": self.config.status.value,
      "charging_complete": charging_complete,
    }

  def to_dict(self) -> dict[str, Any]:
    return self.config.model_dump()

  def to_schema(self) -> VirtualEv:
    return self.config.model_copy()

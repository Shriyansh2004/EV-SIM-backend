from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ChargerStatus(str, Enum):
    AVAILABLE = "Available"
    PREPARING = "Preparing"
    CHARGING = "Charging"
    SUSPENDED_EV = "SuspendedEV"
    SUSPENDED_EVSE = "SuspendedEVSE"
    FINISHING = "Finishing"
    RESERVED = "Reserved"
    UNAVAILABLE = "Unavailable"
    FAULTED = "Faulted"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


class MessageDirection(str, Enum):
    CP_TO_CSMS = "CP_TO_CSMS"
    CSMS_TO_CP = "CSMS_TO_CP"


class MessageType(str, Enum):
    REQUEST = "Request"
    RESPONSE = "Response"
    ERROR = "Error"


class ChargerConfig(BaseModel):
    id: str
    max_power_kw: float = 22.0
    connector_count: int = 1


class MeterValue(BaseModel):
    timestamp: str
    power_kw: float = 0.0
    energy_kwh: float = 0.0
    soc_percent: Optional[float] = None
    voltage_v: Optional[float] = None
    current_a: Optional[float] = None


class Session(BaseModel):
    id: str
    charger_id: str
    ev_id: Optional[str] = None
    connector_id: int = 1
    start_time: str
    end_time: Optional[str] = None
    energy_kwh: float = 0.0
    current_power_kw: float = 0.0
    soc_percent: Optional[float] = 20.0
    status: SessionStatus = SessionStatus.ACTIVE
    meter_values: list[MeterValue] = Field(default_factory=list)


class VirtualCharger(BaseModel):
    id: str
    status: ChargerStatus = ChargerStatus.AVAILABLE
    connector_count: int = 1
    max_power_kw: float = 22.0
    is_connected: bool = False
    current_session: Optional[Session] = None
    last_heartbeat: Optional[str] = None
    connector_statuses: list[ChargerStatus] = Field(default_factory=list)
    plugged_evs: dict[str, Optional[str]] = Field(default_factory=dict)


class OcppMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    charger_id: str
    direction: MessageDirection
    message_type: MessageType
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = None


class CreateChargerRequest(BaseModel):
    id: str
    max_power_kw: float = 22.0
    connector_count: int = 1


class StartSessionRequest(BaseModel):
    charger_id: str
    connector_id: int = 1
    id_token: str = "DEMO-TOKEN"


class StopSessionRequest(BaseModel):
    charger_id: str
    session_id: Optional[str] = None


class ResetRequest(BaseModel):
    charger_id: str
    reset_type: Literal["Immediate", "OnIdle"] = "Immediate"


class AvailabilityRequest(BaseModel):
    charger_id: str
    connector_id: int = 0
    operational_status: Literal["Operative", "Inoperative"] = "Operative"


class UnlockRequest(BaseModel):
    charger_id: str
    connector_id: int = 1


class WsEvent(BaseModel):
    type: str
    data: dict[str, Any]


class EvStatus(str, Enum):
    IDLE = "idle"
    PLUGGED = "plugged"
    CHARGING = "charging"
    FULL = "full"
    FAULT = "fault"


class EvType(str, Enum):
    BEV = "BEV"
    PHEV = "PHEV"
    HEV = "HEV"


class VirtualEv(BaseModel):
    id: str
    name: str
    vendor: str
    model: str
    ev_type: EvType = EvType.BEV
    battery_capacity_kwh: float = 75.0
    max_charge_power_kw: float = 11.0
    max_ac_charge_power_kw: float = 11.0
    max_dc_charge_power_kw: float = 150.0
    soc_percent: float = 20.0
    target_soc_percent: float = 80.0
    status: EvStatus = EvStatus.IDLE
    charger_id: Optional[str] = None
    connector_id: Optional[int] = None
    session_id: Optional[str] = None
    energy_charged_kwh: float = 0.0
    current_power_kw: float = 0.0
    voltage_v: float = 0.0
    current_a: float = 0.0
    created_at: str


class CreateEvRequest(BaseModel):
    id: str
    name: Optional[str] = None
    vendor: str = "Generic"
    model: str = "EV"
    ev_type: EvType = EvType.BEV
    battery_capacity_kwh: float = 75.0
    max_ac_charge_power_kw: float = 11.0
    max_dc_charge_power_kw: float = 150.0
    soc_percent: float = 20.0
    target_soc_percent: float = 80.0


class PlugEvRequest(BaseModel):
    charger_id: str
    connector_id: int = 1


class EvPreset(BaseModel):
    id: str
    name: str
    vendor: str
    model: str
    ev_type: EvType
    battery_capacity_kwh: float
    max_ac_charge_power_kw: float
    max_dc_charge_power_kw: float

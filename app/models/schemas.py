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

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ChargerRecord(Base):
  __tablename__ = "chargers"

  id: Mapped[str] = mapped_column(String, primary_key=True)
  max_power_kw: Mapped[float] = mapped_column(Float, default=22.0)
  connector_count: Mapped[int] = mapped_column(Integer, default=1)
  status: Mapped[str] = mapped_column(String, default="Available")
  connector_statuses: Mapped[list] = mapped_column(JSONB, default=list)
  last_heartbeat: Mapped[str | None] = mapped_column(String, nullable=True)


class SessionRecord(Base):
  __tablename__ = "sessions"

  id: Mapped[str] = mapped_column(String, primary_key=True)
  charger_id: Mapped[str] = mapped_column(
    String, ForeignKey("chargers.id", ondelete="CASCADE"), index=True
  )
  connector_id: Mapped[int] = mapped_column(Integer, default=1)
  start_time: Mapped[str] = mapped_column(String)
  end_time: Mapped[str | None] = mapped_column(String, nullable=True)
  energy_kwh: Mapped[float] = mapped_column(Float, default=0.0)
  current_power_kw: Mapped[float] = mapped_column(Float, default=0.0)
  soc_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
  status: Mapped[str] = mapped_column(String, default="active")

  meter_values: Mapped[list[MeterValueRecord]] = relationship(
    back_populates="session",
    cascade="all, delete-orphan",
    order_by="MeterValueRecord.id",
  )


class MeterValueRecord(Base):
  __tablename__ = "meter_values"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  session_id: Mapped[str] = mapped_column(
    String, ForeignKey("sessions.id", ondelete="CASCADE"), index=True
  )
  timestamp: Mapped[str] = mapped_column(String)
  power_kw: Mapped[float] = mapped_column(Float, default=0.0)
  energy_kwh: Mapped[float] = mapped_column(Float, default=0.0)
  soc_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
  voltage_v: Mapped[float | None] = mapped_column(Float, nullable=True)
  current_a: Mapped[float | None] = mapped_column(Float, nullable=True)

  session: Mapped[SessionRecord] = relationship(back_populates="meter_values")

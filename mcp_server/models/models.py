"""Modelli SQLAlchemy — schema definito nel piano tecnico."""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class Field(Base):
    __tablename__ = "fields"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    cols: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    crop_type: Mapped[str] = mapped_column(Text, nullable=False, default="vite")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    simulation_time: Mapped[datetime] = mapped_column(nullable=False)
    # Posizione corrente del riquadro di supervisione dell'agente
    focus_x: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    focus_y: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    cells: Mapped[list["FieldCell"]] = relationship(back_populates="field")


class FieldCell(Base):
    __tablename__ = "field_cells"
    __table_args__ = (UniqueConstraint("field_id", "x", "y", name="uq_field_cell_xy"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id"), nullable=False)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    soil_moisture: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    soil_temperature: Mapped[float] = mapped_column(Float, nullable=False, default=18.0)
    nutrient_index: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    health_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    disease_risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    active_disease_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("disease_catalog.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="healthy")
    last_inspected_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_photo_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    field: Mapped["Field"] = relationship(back_populates="cells")
    active_disease: Mapped["DiseaseCatalog | None"] = relationship()


class WeatherDaily(Base):
    __tablename__ = "weather_daily"
    __table_args__ = (
        UniqueConstraint("field_id", "sim_date", "is_forecast", name="uq_weather_field_date_fc"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id"), nullable=False)
    sim_date: Mapped[date] = mapped_column(Date, nullable=False)
    rainfall_mm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    humidity_pct: Mapped[float] = mapped_column(Float, nullable=False, default=60.0)
    temp_min: Mapped[float] = mapped_column(Float, nullable=False)
    temp_max: Mapped[float] = mapped_column(Float, nullable=False)
    is_forecast: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class DiseaseCatalog(Base):
    __tablename__ = "disease_catalog"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    pathogen_type: Mapped[str] = mapped_column(Text, nullable=False)
    crop_type: Mapped[str] = mapped_column(Text, nullable=False, default="vite")
    symptoms_visible: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    favorable_temp_min: Mapped[float] = mapped_column(Float, nullable=False)
    favorable_temp_max: Mapped[float] = mapped_column(Float, nullable=False)
    favorable_humidity_min: Mapped[float] = mapped_column(Float, nullable=False)
    spread_speed: Mapped[str] = mapped_column(Text, nullable=False)
    severity_score: Mapped[int] = mapped_column(Integer, nullable=False)
    treatment_duration_h: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    image_folder: Mapped[str] = mapped_column(Text, nullable=False)


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id"), nullable=False)
    cell_x: Mapped[int] = mapped_column(Integer, nullable=False)
    cell_y: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False, default="agent")
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    cell_x: Mapped[int] = mapped_column(Integer, nullable=False)
    cell_y: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="in_progress")
    started_at_sim: Mapped[datetime] = mapped_column(nullable=False)
    ends_at_sim: Mapped[datetime] = mapped_column(nullable=False)
    completed_at_sim: Mapped[datetime | None] = mapped_column(nullable=True)
    result_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class FieldEvent(Base):
    __tablename__ = "field_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    cell_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cell_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sim_time: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id"), nullable=False)
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

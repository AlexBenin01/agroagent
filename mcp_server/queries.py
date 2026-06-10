"""Query e serializzazione condivise tra endpoint REST e tool MCP."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    AgentTask,
    Checkpoint,
    DiseaseCatalog,
    Field,
    FieldCell,
    FieldEvent,
    WeatherDaily,
)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


async def get_field_or_error(session: AsyncSession, field_id: str) -> Field:
    try:
        fid = uuid.UUID(field_id)
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"field_id non valido: {field_id!r}")
    field = await session.get(Field, fid)
    if field is None:
        raise ValueError(f"Campo {field_id} inesistente")
    return field


def validate_coords(field: Field, x: int, y: int) -> None:
    if not (0 <= x < field.cols and 0 <= y < field.rows):
        raise ValueError(
            f"Coordinate ({x},{y}) fuori dalla griglia {field.cols}x{field.rows} "
            f"(x: 0-{field.cols - 1}, y: 0-{field.rows - 1})"
        )


async def get_cell_or_error(session: AsyncSession, field: Field, x: int, y: int) -> FieldCell:
    validate_coords(field, x, y)
    result = await session.execute(
        select(FieldCell).where(
            FieldCell.field_id == field.id, FieldCell.x == x, FieldCell.y == y
        )
    )
    return result.scalar_one()


def serialize_field(field: Field) -> dict:
    return {
        "id": str(field.id),
        "name": field.name,
        "rows": field.rows,
        "cols": field.cols,
        "crop_type": field.crop_type,
        "sim_time": iso(field.simulation_time),
        "focus": {"x": field.focus_x, "y": field.focus_y},
    }


def serialize_cell(cell: FieldCell, disease_names: dict | None = None) -> dict:
    disease_name = None
    if cell.active_disease_id is not None and disease_names:
        disease_name = disease_names.get(cell.active_disease_id)
    return {
        "x": cell.x,
        "y": cell.y,
        "soil_moisture": round(cell.soil_moisture, 3),
        "soil_temperature": round(cell.soil_temperature, 1),
        "nutrient_index": round(cell.nutrient_index, 3),
        "health_score": round(cell.health_score, 3),
        "disease_risk_score": round(cell.disease_risk_score, 3),
        "status": cell.status,
        "active_disease": disease_name,
        "last_inspected_at": iso(cell.last_inspected_at),
        "last_photo_path": cell.last_photo_path,
    }


def serialize_disease(d: DiseaseCatalog) -> dict:
    return {
        "id": str(d.id),
        "name": d.name,
        "pathogen_type": d.pathogen_type,
        "crop_type": d.crop_type,
        "symptoms_visible": d.symptoms_visible,
        "favorable_temp_min": d.favorable_temp_min,
        "favorable_temp_max": d.favorable_temp_max,
        "favorable_humidity_min": d.favorable_humidity_min,
        "spread_speed": d.spread_speed,
        "severity_score": d.severity_score,
        "treatment_duration_h": d.treatment_duration_h,
        "recommended_action": d.recommended_action,
    }


def serialize_task(t: AgentTask) -> dict:
    return {
        "id": str(t.id),
        "task_type": t.task_type,
        "x": t.cell_x,
        "y": t.cell_y,
        "status": t.status,
        "started_at_sim": iso(t.started_at_sim),
        "ends_at_sim": iso(t.ends_at_sim),
        "completed_at_sim": iso(t.completed_at_sim),
        "result_note": t.result_note,
    }


def serialize_checkpoint(c: Checkpoint) -> dict:
    return {
        "id": str(c.id),
        "x": c.cell_x,
        "y": c.cell_y,
        "type": c.type,
        "note": c.note,
        "created_by": c.created_by,
        "created_at": iso(c.created_at),
        "resolved": c.resolved,
    }


def serialize_event(e: FieldEvent) -> dict:
    return {
        "id": str(e.id),
        "event_type": e.event_type,
        "x": e.cell_x,
        "y": e.cell_y,
        "description": e.description,
        "sim_time": iso(e.sim_time),
        "created_at": iso(e.created_at),
    }


def serialize_weather(w: WeatherDaily) -> dict:
    return {
        "sim_date": w.sim_date.isoformat(),
        "rainfall_mm": w.rainfall_mm,
        "humidity_pct": w.humidity_pct,
        "temp_min": w.temp_min,
        "temp_max": w.temp_max,
        "is_forecast": w.is_forecast,
    }


async def disease_names_map(session: AsyncSession) -> dict:
    result = await session.execute(select(DiseaseCatalog.id, DiseaseCatalog.name))
    return {row.id: row.name for row in result}


async def current_weather(session: AsyncSession, field: Field) -> dict | None:
    """Meteo effettivo più recente non oltre la data simulata corrente."""
    sim_date = field.simulation_time.date()
    result = await session.execute(
        select(WeatherDaily)
        .where(
            WeatherDaily.field_id == field.id,
            WeatherDaily.is_forecast.is_(False),
            WeatherDaily.sim_date <= sim_date,
        )
        .order_by(WeatherDaily.sim_date.desc())
        .limit(1)
    )
    w = result.scalar_one_or_none()
    return serialize_weather(w) if w else None


async def weather_forecast(session: AsyncSession, field: Field, days: int = 7) -> list[dict]:
    sim_date = field.simulation_time.date()
    result = await session.execute(
        select(WeatherDaily)
        .where(
            WeatherDaily.field_id == field.id,
            WeatherDaily.is_forecast.is_(True),
            WeatherDaily.sim_date > sim_date,
        )
        .order_by(WeatherDaily.sim_date)
        .limit(days)
    )
    return [serialize_weather(w) for w in result.scalars()]


async def field_state(session: AsyncSession, field: Field) -> dict:
    names = await disease_names_map(session)

    cells_result = await session.execute(
        select(FieldCell)
        .where(FieldCell.field_id == field.id)
        .order_by(FieldCell.y, FieldCell.x)
    )
    cells = [serialize_cell(c, names) for c in cells_result.scalars()]

    tasks_result = await session.execute(
        select(AgentTask).where(
            AgentTask.field_id == field.id, AgentTask.status == "in_progress"
        )
    )
    tasks = [serialize_task(t) for t in tasks_result.scalars()]

    cp_result = await session.execute(
        select(Checkpoint).where(
            Checkpoint.field_id == field.id, Checkpoint.resolved.is_(False)
        )
    )
    checkpoints = [serialize_checkpoint(c) for c in cp_result.scalars()]

    return {
        "field": serialize_field(field),
        "cells": cells,
        "weather": {
            "current": await current_weather(session, field),
            "forecast": await weather_forecast(session, field),
        },
        "active_tasks": tasks,
        "open_checkpoints": checkpoints,
    }


async def cell_detail(session: AsyncSession, field: Field, x: int, y: int) -> dict:
    cell = await get_cell_or_error(session, field, x, y)

    disease = None
    if cell.active_disease_id is not None:
        d = await session.get(DiseaseCatalog, cell.active_disease_id)
        disease = serialize_disease(d) if d else None

    events_result = await session.execute(
        select(FieldEvent)
        .where(
            FieldEvent.field_id == field.id,
            FieldEvent.cell_x == x,
            FieldEvent.cell_y == y,
        )
        .order_by(FieldEvent.created_at.desc())
        .limit(10)
    )
    events = [serialize_event(e) for e in events_result.scalars()]

    tasks_result = await session.execute(
        select(AgentTask).where(
            AgentTask.field_id == field.id,
            AgentTask.cell_x == x,
            AgentTask.cell_y == y,
            AgentTask.status == "in_progress",
        )
    )
    tasks = [serialize_task(t) for t in tasks_result.scalars()]

    cp_result = await session.execute(
        select(Checkpoint).where(
            Checkpoint.field_id == field.id,
            Checkpoint.cell_x == x,
            Checkpoint.cell_y == y,
            Checkpoint.resolved.is_(False),
        )
    )
    checkpoints = [serialize_checkpoint(c) for c in cp_result.scalars()]

    names = await disease_names_map(session)
    return {
        "cell": serialize_cell(cell, names),
        "active_disease": disease,
        "recent_events": events,
        "active_tasks": tasks,
        "open_checkpoints": checkpoints,
        "sim_time": iso(field.simulation_time),
    }


async def recent_events(session: AsyncSession, field: Field, limit: int = 20) -> list[dict]:
    result = await session.execute(
        select(FieldEvent)
        .where(FieldEvent.field_id == field.id)
        .order_by(FieldEvent.created_at.desc())
        .limit(limit)
    )
    return [serialize_event(e) for e in result.scalars()]


async def weather_summary(session: AsyncSession, field: Field, days_back: int = 7) -> dict:
    sim_date = field.simulation_time.date()
    since = sim_date - timedelta(days=days_back)
    result = await session.execute(
        select(WeatherDaily)
        .where(
            WeatherDaily.field_id == field.id,
            WeatherDaily.is_forecast.is_(False),
            WeatherDaily.sim_date > since,
            WeatherDaily.sim_date <= sim_date,
        )
        .order_by(WeatherDaily.sim_date)
    )
    history = list(result.scalars())
    forecast = await weather_forecast(session, field)

    summary = {
        "days_back": days_back,
        "sim_date": sim_date.isoformat(),
        "history": [serialize_weather(w) for w in history],
        "forecast": forecast,
    }
    if history:
        summary["total_rainfall_mm"] = round(sum(w.rainfall_mm for w in history), 1)
        summary["avg_humidity_pct"] = round(
            sum(w.humidity_pct for w in history) / len(history), 1
        )
        summary["temp_min"] = min(w.temp_min for w in history)
        summary["temp_max"] = max(w.temp_max for w in history)
    return summary

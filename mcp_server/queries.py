"""Query e serializzazione condivise tra endpoint REST e tool MCP."""
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config

from models import (
    AgentTask,
    Checkpoint,
    DiseaseCatalog,
    Field,
    FieldCell,
    FieldEvent,
    FieldInventory,
    ProductCatalog,
    ProductOrder,
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
        "difficulty": field.difficulty,
        "time_speed": field.time_speed,
    }


def _photo_url(last_photo_path: str | None) -> str | None:
    """URL pronto della foto della cella: le foto caricate hanno già un path
    assoluto (/uploads/...), quelle del dataset sono relative a /images."""
    if not last_photo_path:
        return None
    return last_photo_path if last_photo_path.startswith("/") else f"/images/{last_photo_path}"


def serialize_cell(
    cell: FieldCell,
    disease_names: dict | None = None,
    disease_images: dict | None = None,
) -> dict:
    disease_name = None
    if cell.active_disease_id is not None and disease_names:
        disease_name = disease_names.get(cell.active_disease_id)
    disease_image_url = None
    if cell.active_disease_id is not None and disease_images:
        disease_image_url = disease_images.get(cell.active_disease_id)
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
        "last_photo_url": _photo_url(cell.last_photo_path),
        # immagine di riferimento della malattia attiva (mostrata anche se la
        # cella non è mai stata fotografata)
        "disease_image_url": disease_image_url,
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


# cache cartella-malattia -> URL immagine rappresentativa (/images/diseased/...)
_REP_IMAGE_CACHE: dict[str, str | None] = {}


def _representative_image_url(image_folder: str) -> str | None:
    if image_folder in _REP_IMAGE_CACHE:
        return _REP_IMAGE_CACHE[image_folder]
    folder = Path(config.IMAGE_BASE_PATH) / "diseased" / image_folder
    rel = None
    if folder.is_dir():
        files = sorted(
            p for p in folder.glob("*")
            if p.suffix.lower() in (".jpg", ".jpeg", ".png")
        )
        if files:
            rel = f"/images/diseased/{image_folder}/{files[0].name}"
    _REP_IMAGE_CACHE[image_folder] = rel
    return rel


async def disease_image_map(session: AsyncSession) -> dict:
    """id malattia -> URL di un'immagine rappresentativa (per mostrare la foto
    della malattia anche su una cella mai fotografata)."""
    result = await session.execute(
        select(DiseaseCatalog.id, DiseaseCatalog.image_folder)
    )
    return {row.id: _representative_image_url(row.image_folder) for row in result}


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
    images = await disease_image_map(session)

    cells_result = await session.execute(
        select(FieldCell)
        .where(FieldCell.field_id == field.id)
        .order_by(FieldCell.y, FieldCell.x)
    )
    cells = [serialize_cell(c, names, images) for c in cells_result.scalars()]

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


async def field_summary(session: AsyncSession, field: Field, top_n: int = 8) -> dict:
    """Riassunto compatto del campo per l'agente LLM: conteggi per stato, meteo
    corrente, task attivi e le celle più critiche (malate / a rischio) con le
    coordinate. Evita di riversare tutte le 100 celle nel contesto del modello;
    per il dettaglio di una cella si usa get_cell_detail."""
    names = await disease_names_map(session)
    cells = list(
        (
            await session.execute(
                select(FieldCell).where(FieldCell.field_id == field.id)
            )
        ).scalars()
    )
    status_counts: dict[str, int] = {}
    for c in cells:
        status_counts[c.status] = status_counts.get(c.status, 0) + 1

    # celle critiche: prima le malate (salute crescente), poi le a rischio
    diseased = sorted(
        (c for c in cells if c.status in ("diseased", "under_treatment")),
        key=lambda c: c.health_score,
    )
    at_risk = sorted(
        (c for c in cells if c.status == "at_risk"),
        key=lambda c: -c.disease_risk_score,
    )
    critical = [
        {
            "x": c.x, "y": c.y, "status": c.status,
            "health_score": round(c.health_score, 3),
            "disease_risk_score": round(c.disease_risk_score, 3),
            "active_disease": names.get(c.active_disease_id) if c.active_disease_id else None,
        }
        for c in (diseased + at_risk)[:top_n]
    ]

    tasks = list(
        (
            await session.execute(
                select(AgentTask).where(
                    AgentTask.field_id == field.id, AgentTask.status == "in_progress"
                )
            )
        ).scalars()
    )

    return {
        "field": serialize_field(field),
        "sim_time": iso(field.simulation_time),
        "grid": {"rows": field.rows, "cols": field.cols, "total_cells": len(cells)},
        "status_counts": status_counts,
        "critical_cells": critical,
        "active_tasks": [serialize_task(t) for t in tasks],
        "weather_current": await current_weather(session, field),
        "hint": "Usa get_cell_detail(x,y) per il dettaglio di una cella specifica.",
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
    images = await disease_image_map(session)
    return {
        "cell": serialize_cell(cell, names, images),
        "active_disease": disease,
        "recent_events": events,
        "active_tasks": tasks,
        "open_checkpoints": checkpoints,
        "sim_time": iso(field.simulation_time),
    }


def serialize_product(p: ProductCatalog) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "product_type": p.product_type,
        "targets": p.targets,
        "delivery_min_h": p.delivery_min_h,
        "delivery_max_h": p.delivery_max_h,
        "efficacy": p.efficacy,
        "description": p.description,
    }


async def get_product_or_error(session: AsyncSession, product_id: str) -> ProductCatalog:
    try:
        pid = uuid.UUID(product_id)
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"product_id non valido: {product_id!r}")
    product = await session.get(ProductCatalog, pid)
    if product is None:
        raise ValueError(f"Prodotto {product_id} inesistente")
    return product


async def inventory_state(session: AsyncSession, field: Field) -> dict:
    """Catalogo prodotti con stock attuale nel campo + ordini in transito (ETA)."""
    products = list((await session.execute(select(ProductCatalog))).scalars())
    stock_rows = (
        await session.execute(
            select(FieldInventory).where(FieldInventory.field_id == field.id)
        )
    ).scalars()
    qty_by_product = {row.product_id: row.quantity for row in stock_rows}

    orders = (
        await session.execute(
            select(ProductOrder).where(
                ProductOrder.field_id == field.id,
                ProductOrder.status == "in_transit",
            )
        )
    ).scalars()
    sim_time = field.simulation_time
    pending = []
    name_by_id = {p.id: p.name for p in products}
    for o in orders:
        eta_h = round((o.arrives_at_sim - sim_time).total_seconds() / 3600, 1)
        pending.append({
            "order_id": str(o.id),
            "product_id": str(o.product_id),
            "product_name": name_by_id.get(o.product_id, "?"),
            "quantity": o.quantity,
            "arrives_at_sim": iso(o.arrives_at_sim),
            "eta_hours": max(0.0, eta_h),
        })

    catalog = []
    for p in products:
        item = serialize_product(p)
        item["in_stock"] = qty_by_product.get(p.id, 0)
        catalog.append(item)

    return {
        "sim_time": iso(sim_time),
        "products": catalog,
        "pending_orders": pending,
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

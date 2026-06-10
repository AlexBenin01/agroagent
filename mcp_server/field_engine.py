"""Motore di simulazione del campo.

run_field_tick avanza l'orologio simulato di N ore dentro una transazione
protetta da advisory lock Postgres per field_id: il tick di background e
advance_simulation_time non possono mai sovrapporsi sullo stesso campo.

Tutti i timestamp dei task sono in tempo simulato: un task si chiude quando
sim_time >= ends_at_sim, mai con timer reali.
"""
import logging
import random
import uuid
from datetime import date, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import queries
from db.session import SessionLocal
from models import AgentTask, DiseaseCatalog, Field, FieldCell, FieldEvent, WeatherDaily
from sse import broker
from weather_gen import generate_weather_day

logger = logging.getLogger("field_engine")

FORECAST_DAYS = 7
HEAVY_RAIN_MM = 10.0
RISK_ACTIVATION_THRESHOLD = 0.85
AT_RISK_THRESHOLD = 0.6
# perdita di salute per ora simulata, per velocità di diffusione della malattia
SPREAD_DECAY_PER_H = {"slow": 0.002, "medium": 0.004, "fast": 0.007}
RECOVERY_PER_H = 0.003  # recupero celle 'treated'
MOISTURE_PER_MM_RAIN = 0.015
EVAPORATION_PER_H = 0.005


def _neighbors(x: int, y: int, cols: int, rows: int) -> list[tuple[int, int]]:
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if 0 <= nx < cols and 0 <= ny < rows:
                out.append((nx, ny))
    return out


async def _advance_weather(
    session: AsyncSession,
    field: Field,
    start_date: date,
    end_date: date,
    rng: random.Random,
    events: list[FieldEvent],
    sim_time,
) -> None:
    """Promuove le previsioni in dati effettivi per i giorni attraversati
    e mantiene 7 giorni di forecast oltre la data corrente."""
    result = await session.execute(
        select(WeatherDaily).where(WeatherDaily.field_id == field.id)
    )
    by_key = {(w.sim_date, w.is_forecast): w for w in result.scalars()}

    day = start_date + timedelta(days=1)
    while day <= end_date:
        if (day, False) not in by_key:
            forecast = by_key.get((day, True))
            values = (
                {
                    "sim_date": day,
                    "rainfall_mm": forecast.rainfall_mm,
                    "humidity_pct": forecast.humidity_pct,
                    "temp_min": forecast.temp_min,
                    "temp_max": forecast.temp_max,
                }
                if forecast
                else generate_weather_day(rng, day)
            )
            actual = WeatherDaily(field_id=field.id, is_forecast=False, **values)
            session.add(actual)
            by_key[(day, False)] = actual
            if values["rainfall_mm"] >= HEAVY_RAIN_MM:
                events.append(
                    FieldEvent(
                        field_id=field.id,
                        event_type="rain",
                        description=(
                            f"Pioggia abbondante: {values['rainfall_mm']:.0f} mm il {day.isoformat()}"
                        ),
                        sim_time=sim_time,
                    )
                )
        day += timedelta(days=1)

    # elimina forecast ormai nel passato
    await session.execute(
        delete(WeatherDaily).where(
            WeatherDaily.field_id == field.id,
            WeatherDaily.is_forecast.is_(True),
            WeatherDaily.sim_date <= end_date,
        )
    )
    # estende le previsioni fino a +7 giorni
    for offset in range(1, FORECAST_DAYS + 1):
        day = end_date + timedelta(days=offset)
        if (day, True) not in by_key and (day, False) not in by_key:
            session.add(
                WeatherDaily(
                    field_id=field.id, is_forecast=True, **generate_weather_day(rng, day)
                )
            )


def _disease_risk(
    cell: FieldCell,
    disease: DiseaseCatalog,
    humidity: float,
    avg_temp: float,
    diseased_neighbor: bool,
) -> float:
    risk = 0.05
    if cell.soil_moisture > 0.7:
        risk += 0.3
    if humidity > 80:
        risk += 0.2
    if disease.favorable_temp_min <= avg_temp <= disease.favorable_temp_max:
        risk += 0.3
    if diseased_neighbor:
        risk += 0.4
    return min(1.0, risk)


async def run_field_tick(session: AsyncSession, field_id: uuid.UUID, delta_hours: int) -> dict:
    """Avanza la simulazione. Da chiamare dentro una sessione; il chiamante
    committa e poi pubblica gli eventi SSE (mai prima del commit)."""
    # 0. advisory lock transazionale sul campo
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:fid))"), {"fid": str(field_id)}
    )
    field = await session.get(Field, field_id)
    if field is None:
        raise ValueError(f"Campo {field_id} inesistente")

    rng = random.Random()
    old_sim = field.simulation_time
    new_sim = old_sim + timedelta(hours=delta_hours)
    field.simulation_time = new_sim
    events: list[FieldEvent] = []

    # 1. meteo
    await _advance_weather(
        session, field, old_sim.date(), new_sim.date(), rng, events, new_sim
    )

    # dati meteo del giorno corrente + pioggia caduta nel periodo
    weather_rows = (
        await session.execute(
            select(WeatherDaily).where(
                WeatherDaily.field_id == field.id,
                WeatherDaily.is_forecast.is_(False),
                WeatherDaily.sim_date >= old_sim.date(),
                WeatherDaily.sim_date <= new_sim.date(),
            )
        )
    ).scalars().all()
    today = next((w for w in weather_rows if w.sim_date == new_sim.date()), None)
    humidity = today.humidity_pct if today else 60.0
    avg_temp = (today.temp_min + today.temp_max) / 2 if today else 20.0
    day_fraction = min(1.0, delta_hours / 24.0)
    rain_mm = sum(w.rainfall_mm for w in weather_rows) * day_fraction

    diseases = (await session.execute(select(DiseaseCatalog))).scalars().all()
    disease_by_id = {d.id: d for d in diseases}

    # 2. chiusura task scaduti
    expired = (
        await session.execute(
            select(AgentTask).where(
                AgentTask.field_id == field.id,
                AgentTask.status == "in_progress",
                AgentTask.ends_at_sim <= new_sim,
            )
        )
    ).scalars().all()

    cells = (
        await session.execute(select(FieldCell).where(FieldCell.field_id == field.id))
    ).scalars().all()
    cell_at = {(c.x, c.y): c for c in cells}

    completed_tasks = []
    for task in expired:
        task.status = "completed"
        task.completed_at_sim = task.ends_at_sim
        cell = cell_at.get((task.cell_x, task.cell_y))
        if cell is not None:
            if task.task_type == "irrigation":
                cell.soil_moisture = min(0.85, cell.soil_moisture + 0.35)
                task.result_note = "Irrigazione completata"
            else:
                disease = disease_by_id.get(cell.active_disease_id)
                cell.active_disease_id = None
                cell.health_score = max(cell.health_score, 0.7)
                cell.status = "treated"
                task.result_note = (
                    f"Trattamento completato"
                    + (f" contro {disease.name}" if disease else "")
                )
        events.append(
            FieldEvent(
                field_id=field.id,
                event_type="treatment_completed",
                cell_x=task.cell_x,
                cell_y=task.cell_y,
                description=task.result_note or "Task completato",
                sim_time=new_sim,
            )
        )
        completed_tasks.append(task)

    # celle con un task di cura ancora in corso (non subiscono decadimento)
    in_progress = (
        await session.execute(
            select(AgentTask).where(
                AgentTask.field_id == field.id, AgentTask.status == "in_progress"
            )
        )
    ).scalars().all()
    under_care = {(t.cell_x, t.cell_y) for t in in_progress if t.task_type != "irrigation"}

    diseased_coords = {
        (c.x, c.y): c.active_disease_id for c in cells if c.active_disease_id is not None
    }
    # celle il cui trattamento si è chiuso in QUESTO tick: il recupero
    # graduale inizia dal tick successivo
    just_treated = {
        (t.cell_x, t.cell_y) for t in completed_tasks if t.task_type != "irrigation"
    }

    # 3. aggiornamento celle
    for cell in cells:
        # a. moisture: pioggia assorbita - evaporazione (dipendente dalla temperatura)
        evap = EVAPORATION_PER_H * delta_hours * max(0.3, avg_temp / 20.0)
        cell.soil_moisture = round(
            min(0.95, max(0.05, cell.soil_moisture + rain_mm * MOISTURE_PER_MM_RAIN - evap)),
            3,
        )
        # b. temperatura suolo verso la media aria del giorno
        approach = min(1.0, delta_hours / 24.0) * 0.5
        cell.soil_temperature = round(
            cell.soil_temperature + (avg_temp - cell.soil_temperature) * approach
            + rng.uniform(-0.3, 0.3),
            1,
        )

        # c. rischio malattia (max sulle malattie compatibili)
        neighbor_diseases = {
            diseased_coords[(nx, ny)]
            for nx, ny in _neighbors(cell.x, cell.y, field.cols, field.rows)
            if (nx, ny) in diseased_coords
        }
        best_risk, best_disease = 0.0, None
        for disease in diseases:
            risk = _disease_risk(
                cell, disease, humidity, avg_temp, disease.id in neighbor_diseases
            )
            if risk > best_risk:
                best_risk, best_disease = risk, disease
        cell.disease_risk_score = round(best_risk, 3)

        if cell.active_disease_id is None and cell.status not in ("under_treatment",):
            if best_risk > RISK_ACTIVATION_THRESHOLD and best_disease is not None:
                cell.active_disease_id = best_disease.id
                cell.status = "diseased"
                events.append(
                    FieldEvent(
                        field_id=field.id,
                        event_type="disease_detected",
                        cell_x=cell.x,
                        cell_y=cell.y,
                        description=(
                            f"{best_disease.name} rilevata nella cella ({cell.x},{cell.y})"
                        ),
                        sim_time=new_sim,
                    )
                )
            elif cell.status in ("healthy", "at_risk"):
                cell.status = "at_risk" if best_risk >= AT_RISK_THRESHOLD else "healthy"
            elif cell.status == "treated" and (cell.x, cell.y) not in just_treated:
                cell.health_score = round(
                    min(0.95, cell.health_score + RECOVERY_PER_H * delta_hours), 3
                )
                if cell.health_score >= 0.9:
                    cell.status = "healthy"

        # d. decadimento salute se malata e senza cura in corso
        if cell.active_disease_id is not None and (cell.x, cell.y) not in under_care:
            disease = disease_by_id.get(cell.active_disease_id)
            decay = SPREAD_DECAY_PER_H.get(disease.spread_speed, 0.004) if disease else 0.004
            before = cell.health_score
            cell.health_score = round(max(0.05, cell.health_score - decay * delta_hours), 3)
            if before >= 0.25 > cell.health_score:
                events.append(
                    FieldEvent(
                        field_id=field.id,
                        event_type="disease_detected",
                        cell_x=cell.x,
                        cell_y=cell.y,
                        description=(
                            f"Salute critica nella cella ({cell.x},{cell.y}): "
                            f"{cell.health_score:.2f}"
                        ),
                        sim_time=new_sim,
                    )
                )

    # 4. evento di avanzamento tempo
    events.append(
        FieldEvent(
            field_id=field.id,
            event_type="time_advance",
            description=f"Tempo simulato avanzato di {delta_hours}h",
            sim_time=new_sim,
        )
    )
    for event in events:
        session.add(event)

    return {
        "new_sim_time": new_sim,
        "delta_hours": delta_hours,
        "events": [queries.serialize_event(e) for e in events],
        "completed_tasks": [queries.serialize_task(t) for t in completed_tasks],
    }


async def advance_field_and_publish(field_id: str, hours: int) -> dict:
    """Esegue il tick, committa e solo dopo pubblica gli eventi SSE."""
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        result = await run_field_tick(session, field.id, hours)
        state = await queries.field_state(session, field)
        await session.commit()

    fid = str(field.id)
    for task in result["completed_tasks"]:
        broker.publish(fid, "task_completed", {"task_id": task["id"], "x": task["x"], "y": task["y"]})
    broker.publish(
        fid,
        "time_advanced",
        {
            "delta_hours": result["delta_hours"],
            "new_sim_time": queries.iso(result["new_sim_time"]),
            "events_generated": result["events"],
        },
    )
    broker.publish(
        fid, "field_update", {"cells": state["cells"], "sim_time": queries.iso(result["new_sim_time"])}
    )
    return {
        "new_sim_time": queries.iso(result["new_sim_time"]),
        "delta_hours": result["delta_hours"],
        "events_generated": result["events"],
        "completed_tasks": result["completed_tasks"],
        "weather": state["weather"],
    }

"""Creazione di un campo: celle, meteo iniziale (storico + forecast), demo infetta."""
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models import DiseaseCatalog, Field, FieldCell, FieldEvent, WeatherDaily
from weather_gen import generate_weather_day

WEATHER_HISTORY_DAYS = 7
FORECAST_DAYS = 7


async def create_field(
    session: AsyncSession,
    name: str,
    rows: int | None = None,
    cols: int | None = None,
    seed_demo_state: bool = True,
) -> Field:
    """Crea campo + celle + meteo. Con seed_demo_state aggiunge un piccolo
    focolaio di peronospora e qualche cella a rischio, per una demo interessante."""
    rows = rows or config.DEFAULT_FIELD_ROWS
    cols = cols or config.DEFAULT_FIELD_COLS
    rng = random.Random()

    sim_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    field = Field(name=name, rows=rows, cols=cols, crop_type="vite", simulation_time=sim_time)
    session.add(field)
    await session.flush()

    # Meteo: storico (oggi compreso) + previsioni
    today = sim_time.date()
    weather_today = None
    for offset in range(-(WEATHER_HISTORY_DAYS - 1), 0 + 1):
        day = generate_weather_day(rng, today + timedelta(days=offset))
        session.add(WeatherDaily(field_id=field.id, is_forecast=False, **day))
        if offset == 0:
            weather_today = day
    for offset in range(1, FORECAST_DAYS + 1):
        day = generate_weather_day(rng, today + timedelta(days=offset))
        session.add(WeatherDaily(field_id=field.id, is_forecast=True, **day))

    avg_temp = (weather_today["temp_min"] + weather_today["temp_max"]) / 2

    cells: dict[tuple[int, int], FieldCell] = {}
    for y in range(rows):
        for x in range(cols):
            cell = FieldCell(
                field_id=field.id,
                x=x,
                y=y,
                soil_moisture=round(rng.uniform(0.35, 0.65), 2),
                soil_temperature=round(avg_temp + rng.uniform(-1.5, 1.5), 1),
                nutrient_index=round(rng.uniform(0.5, 0.9), 2),
                health_score=round(rng.uniform(0.9, 1.0), 2),
                disease_risk_score=round(rng.uniform(0.05, 0.3), 2),
                status="healthy",
            )
            cells[(x, y)] = cell
            session.add(cell)

    if seed_demo_state:
        result = await session.execute(
            select(DiseaseCatalog).where(DiseaseCatalog.name == "Peronospora della vite")
        )
        peronospora = result.scalar_one_or_none()
        if peronospora is not None:
            fx = rng.randint(1, cols - 2)
            fy = rng.randint(1, rows - 2)
            for (x, y), health in [((fx, fy), 0.55), ((fx + 1, fy), 0.68)]:
                cell = cells[(x, y)]
                cell.active_disease_id = peronospora.id
                cell.status = "diseased"
                cell.health_score = health
                cell.disease_risk_score = 0.95
                cell.soil_moisture = round(rng.uniform(0.7, 0.85), 2)
                session.add(
                    FieldEvent(
                        field_id=field.id,
                        event_type="disease_detected",
                        cell_x=x,
                        cell_y=y,
                        description=f"Focolaio di {peronospora.name} rilevato nella cella ({x},{y})",
                        sim_time=sim_time,
                    )
                )
            for _ in range(3):
                x, y = rng.randint(0, cols - 1), rng.randint(0, rows - 1)
                cell = cells[(x, y)]
                if cell.status == "healthy":
                    cell.status = "at_risk"
                    cell.disease_risk_score = round(rng.uniform(0.6, 0.8), 2)
                    cell.soil_moisture = round(rng.uniform(0.65, 0.8), 2)

    session.add(
        FieldEvent(
            field_id=field.id,
            event_type="field_created",
            description=f"Campo '{name}' creato ({rows}x{cols} celle, coltura: vite)",
            sim_time=sim_time,
        )
    )
    return field

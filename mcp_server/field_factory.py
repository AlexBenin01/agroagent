"""Creazione di un campo: celle, meteo iniziale (storico + forecast), demo infetta."""
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from field_engine import difficulty_profile
from models import DiseaseCatalog, Field, FieldCell, FieldEvent, WeatherDaily
from weather_gen import generate_weather_day

WEATHER_HISTORY_DAYS = 7
FORECAST_DAYS = 7
VALID_DIFFICULTIES = ("normal", "hard", "apocalypse")


async def create_field(
    session: AsyncSession,
    name: str,
    rows: int | None = None,
    cols: int | None = None,
    seed_demo_state: bool = True,
    difficulty: str = "normal",
) -> Field:
    """Crea campo + celle + meteo. Con seed_demo_state aggiunge un focolaio
    iniziale dimensionato dalla difficoltà e qualche cella a rischio."""
    rows = rows or config.DEFAULT_FIELD_ROWS
    cols = cols or config.DEFAULT_FIELD_COLS
    if difficulty not in VALID_DIFFICULTIES:
        difficulty = "normal"
    profile = difficulty_profile(difficulty)
    rng = random.Random()

    sim_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    field = Field(
        name=name, rows=rows, cols=cols, crop_type="vite",
        simulation_time=sim_time, difficulty=difficulty,
    )
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
        catalog = list(
            (await session.execute(select(DiseaseCatalog))).scalars()
        )
        if catalog:
            # focolaio iniziale dimensionato dalla difficoltà; alle difficoltà
            # più alte salute più bassa e maggiore varietà di malattie
            outbreak = min(profile["outbreak_cells"], rows * cols // 4)
            # in normal un'unica malattia (più leggibile), altrimenti assortite
            default_disease = next(
                (d for d in catalog if d.name.startswith("Marciume nero")), catalog[0]
            )
            health_floor = {"normal": 0.55, "hard": 0.4, "apocalypse": 0.25}.get(
                difficulty, 0.55
            )
            placed = 0
            attempts = 0
            while placed < outbreak and attempts < outbreak * 10:
                attempts += 1
                x, y = rng.randint(0, cols - 1), rng.randint(0, rows - 1)
                cell = cells[(x, y)]
                if cell.status != "healthy":
                    continue
                disease = default_disease if difficulty == "normal" else rng.choice(catalog)
                cell.active_disease_id = disease.id
                cell.status = "diseased"
                cell.health_score = round(rng.uniform(health_floor, health_floor + 0.15), 2)
                cell.disease_risk_score = 0.95
                cell.soil_moisture = round(rng.uniform(0.7, 0.85), 2)
                session.add(
                    FieldEvent(
                        field_id=field.id,
                        event_type="disease_detected",
                        cell_x=x,
                        cell_y=y,
                        description=f"Focolaio di {disease.name} rilevato nella cella ({x},{y})",
                        sim_time=sim_time,
                    )
                )
                placed += 1

            for _ in range(outbreak + 1):
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

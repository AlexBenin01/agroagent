"""Generazione di dati meteo simulati (clima primaverile/estivo temperato)."""
import random
from datetime import date


def generate_weather_day(rng: random.Random, sim_date: date) -> dict:
    """Genera i valori meteo simulati per un giorno."""
    temp_min = round(rng.gauss(14.0, 2.0), 1)
    temp_max = round(temp_min + 8.0 + rng.gauss(0.0, 3.0), 1)
    if temp_max <= temp_min + 2:
        temp_max = temp_min + 2.0

    raining = rng.random() < 0.3
    rainfall_mm = round(rng.expovariate(1 / 8.0), 1) if raining else 0.0

    humidity = rng.gauss(55.0, 8.0) + (25.0 if raining else 0.0)
    humidity_pct = round(min(98.0, max(30.0, humidity)), 1)

    return {
        "sim_date": sim_date,
        "rainfall_mm": rainfall_mm,
        "humidity_pct": humidity_pct,
        "temp_min": temp_min,
        "temp_max": temp_max,
    }

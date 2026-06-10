"""Tool MCP: knowledge base agronomica (catalogo malattie e protocolli)."""
import uuid

from sqlalchemy import select

import queries
from db.session import SessionLocal
from mcp_app import mcp
from models import DiseaseCatalog


@mcp.tool()
async def query_disease_catalog(
    crop_type: str,
    symptoms: list[str] | None = None,
    weather_conditions: dict | None = None,
) -> dict:
    """Cerca nel catalogo le malattie compatibili con i sintomi osservati e le
    condizioni meteo correnti (chiavi opzionali: temp, humidity_pct). Restituisce
    {"matches": [...]} ordinato per punteggio di compatibilità decrescente."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(DiseaseCatalog).where(DiseaseCatalog.crop_type == crop_type)
        )
        diseases = result.scalars().all()

    scored = []
    for disease in diseases:
        score = 0.0
        matched = []
        if symptoms:
            known = [s.lower() for s in disease.symptoms_visible]
            for symptom in symptoms:
                s = symptom.lower().strip()
                if any(s in k or k in s for k in known):
                    matched.append(symptom)
            score += 2.0 * len(matched)
        if weather_conditions:
            temp = weather_conditions.get("temp")
            humidity = weather_conditions.get("humidity_pct")
            if temp is not None and disease.favorable_temp_min <= float(temp) <= disease.favorable_temp_max:
                score += 1.0
            if humidity is not None and float(humidity) >= disease.favorable_humidity_min:
                score += 1.0
        entry = queries.serialize_disease(disease)
        entry["match_score"] = score
        entry["matched_symptoms"] = matched
        scored.append(entry)

    scored.sort(key=lambda d: d["match_score"], reverse=True)
    return {"matches": scored}


@mcp.tool()
async def get_care_protocol(disease_id: str) -> dict:
    """Protocollo di cura completo per una malattia: azione raccomandata,
    durata del trattamento in ore simulate e note agronomiche."""
    try:
        did = uuid.UUID(disease_id)
    except (ValueError, TypeError):
        raise ValueError(f"disease_id non valido: {disease_id!r}")
    async with SessionLocal() as session:
        disease = await session.get(DiseaseCatalog, did)
        if disease is None:
            raise ValueError(f"Malattia {disease_id} inesistente nel catalogo")
        protocol = queries.serialize_disease(disease)
        protocol["notes"] = (
            f"Trattamento consigliato: {disease.recommended_action}. "
            f"Durata stimata: {disease.treatment_duration_h} ore simulate. "
            f"Severità {disease.severity_score}/5, diffusione {disease.spread_speed}."
        )
        return protocol

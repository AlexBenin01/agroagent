"""Tool MCP di osservazione del campo."""
import random
from pathlib import Path

import config
import queries
from db.session import SessionLocal
from mcp_app import mcp
from models import FieldEvent
from sse import broker


@mcp.tool()
async def get_field_state(field_id: str) -> dict:
    """Restituisce un RIASSUNTO compatto dello stato del campo: conteggi delle
    celle per stato, meteo corrente, task attivi e l'elenco delle celle più
    critiche (malate / a rischio) con le coordinate. Per il dettaglio di una
    singola cella usa get_cell_detail(x, y)."""
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        return await queries.field_summary(session, field)


@mcp.tool()
async def get_cell_detail(field_id: str, x: int, y: int) -> dict:
    """Restituisce il dettaglio completo di una singola cella (x,y): sensori,
    malattia attiva con sintomi e protocollo, storico eventi recenti, foto
    più recente, task in corso e checkpoint aperti."""
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        return await queries.cell_detail(session, field, x, y)


@mcp.tool()
async def capture_field_photo(field_id: str, x: int, y: int) -> dict:
    """Simula uno scatto fotografico (drone) sulla cella (x,y): seleziona
    un'immagine rappresentativa dello stato attuale della pianta (sana o con
    la malattia attiva) e la registra come ultima foto della cella.
    Restituisce il path dell'immagine e i metadati."""
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        cell = await queries.get_cell_or_error(session, field, x, y)

        disease = None
        if cell.active_disease_id is not None:
            from models import DiseaseCatalog

            disease = await session.get(DiseaseCatalog, cell.active_disease_id)

        folder = f"diseased/{disease.image_folder}" if disease else "healthy"
        image_dir = Path(config.IMAGE_BASE_PATH) / folder
        candidates = sorted(
            p for p in image_dir.glob("*")
            if p.suffix.lower() in (".jpg", ".jpeg", ".png")
        ) if image_dir.is_dir() else []
        if not candidates:
            raise ValueError(
                f"Nessuna immagine disponibile in {folder}: eseguire "
                "scripts/generate_placeholder_images.py o importare il dataset"
            )
        chosen = random.choice(candidates)
        rel_path = f"{folder}/{chosen.name}"

        cell.last_photo_path = rel_path
        cell.last_inspected_at = field.simulation_time
        session.add(
            FieldEvent(
                field_id=field.id,
                event_type="inspection",
                cell_x=x,
                cell_y=y,
                description=f"Foto simulata scattata sulla cella ({x},{y})"
                + (f" — sintomi compatibili con {disease.name}" if disease else " — vegetazione sana"),
                sim_time=field.simulation_time,
            )
        )
        names = await queries.disease_names_map(session)
        snapshot = queries.serialize_cell(cell, names)
        sim_time = queries.iso(field.simulation_time)
        await session.commit()

    broker.publish(field_id, "field_update", {"cells": [snapshot], "sim_time": sim_time})
    return {
        "photo_path": rel_path,
        "photo_url": f"/images/{rel_path}",
        "cell": snapshot,
        "observed_disease": disease.name if disease else None,
        "sim_time": sim_time,
    }

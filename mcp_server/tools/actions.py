"""Tool MCP di azione sul campo."""
from datetime import timedelta
from typing import Literal

import queries
from db.session import SessionLocal
from mcp_app import mcp
from models import (
    AgentTask,
    Checkpoint,
    DiseaseCatalog,
    FieldEvent,
    FieldInventory,
)
from sqlalchemy import select
from sse import broker

IRRIGATION_DURATION_H = 2


@mcp.tool()
async def move_focus_area(field_id: str, x: int, y: int) -> dict:
    """Sposta il riquadro di supervisione dell'agente sulla cella (x,y),
    registra l'ispezione e aggiorna last_inspected_at. Il client viene
    notificato via SSE."""
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        cell = await queries.get_cell_or_error(session, field, x, y)
        field.focus_x, field.focus_y = x, y
        cell.last_inspected_at = field.simulation_time
        session.add(
            FieldEvent(
                field_id=field.id,
                event_type="inspection",
                cell_x=x,
                cell_y=y,
                description=f"L'agente ha spostato il focus sulla cella ({x},{y})",
                sim_time=field.simulation_time,
            )
        )
        names = await queries.disease_names_map(session)
        snapshot = queries.serialize_cell(cell, names)
        await session.commit()

    broker.publish(field_id, "focus_moved", {"x": x, "y": y})
    return {"focus": {"x": x, "y": y}, "cell": snapshot}


@mcp.tool()
async def create_checkpoint(
    field_id: str,
    x: int,
    y: int,
    checkpoint_type: Literal["disease_found", "high_moisture", "treatment_done", "inspection"],
    note: str,
) -> dict:
    """Crea un checkpoint sulla cella (x,y) per marcare un punto di interesse
    (malattia trovata, umidità alta, trattamento concluso, ispezione)."""
    if len(note) > 500:
        raise ValueError("La nota non può superare 500 caratteri")
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        queries.validate_coords(field, x, y)
        checkpoint = Checkpoint(
            field_id=field.id, cell_x=x, cell_y=y, type=checkpoint_type,
            note=note, created_by="agent",
        )
        session.add(checkpoint)
        session.add(
            FieldEvent(
                field_id=field.id,
                event_type="checkpoint",
                cell_x=x,
                cell_y=y,
                description=f"Checkpoint '{checkpoint_type}': {note}",
                sim_time=field.simulation_time,
            )
        )
        await session.flush()
        serialized = queries.serialize_checkpoint(checkpoint)
        await session.commit()

    broker.publish(
        field_id, "checkpoint_created",
        {"x": x, "y": y, "type": checkpoint_type, "note": note, "id": serialized["id"]},
    )
    return serialized


@mcp.tool()
async def start_treatment(
    field_id: str,
    x: int,
    y: int,
    treatment_type: Literal["chemical", "biological", "irrigation", "pruning"],
    product_id: str | None = None,
) -> dict:
    """Avvia un trattamento sulla cella (x,y). La durata è in ORE SIMULATE:
    il task si chiude quando l'orologio del campo raggiunge ends_at_sim
    (es. avanzando il tempo con advance_simulation_time).
    - chemical/biological: richiede una malattia attiva E un prodotto adatto
      a magazzino (passa product_id; consuma 1 unità). Se manca lo stock,
      usa query_inventory e order_product. Un prodotto più efficace riduce la
      durata del trattamento.
    - pruning: intervento manuale, richiede una malattia attiva, nessun prodotto.
    - irrigation: sempre possibile, durata 2 ore simulate, nessun prodotto."""
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        cell = await queries.get_cell_or_error(session, field, x, y)

        existing = await session.execute(
            select(AgentTask).where(
                AgentTask.field_id == field.id,
                AgentTask.cell_x == x,
                AgentTask.cell_y == y,
                AgentTask.status == "in_progress",
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError(f"C'è già un task in corso sulla cella ({x},{y})")

        if treatment_type == "irrigation":
            duration_h = IRRIGATION_DURATION_H
            task_type = "irrigation"
            description = f"Irrigazione avviata sulla cella ({x},{y})"
        else:
            if cell.active_disease_id is None:
                raise ValueError(
                    f"Nessuna malattia attiva sulla cella ({x},{y}): "
                    "un trattamento richiede una diagnosi. Usa 'irrigation' per irrigare."
                )
            disease = await session.get(DiseaseCatalog, cell.active_disease_id)
            duration_h = disease.treatment_duration_h
            task_type = "treatment"
            product_name = None

            if treatment_type in ("chemical", "biological"):
                if product_id is None:
                    raise ValueError(
                        "Un trattamento chimico/biologico richiede un prodotto: "
                        "usa query_inventory per scegliere il product_id adatto a "
                        f"{disease.name} ({disease.pathogen_type}) e passalo a start_treatment. "
                        "Se non hai stock, ordina con order_product."
                    )
                product = await queries.get_product_or_error(session, product_id)
                if disease.pathogen_type not in product.targets and "any" not in product.targets:
                    raise ValueError(
                        f"Il prodotto '{product.name}' non è indicato contro "
                        f"{disease.name} ({disease.pathogen_type}). Scegline uno con il "
                        "patogeno fra i target (vedi query_inventory)."
                    )
                stock = (
                    await session.execute(
                        select(FieldInventory).where(
                            FieldInventory.field_id == field.id,
                            FieldInventory.product_id == product.id,
                        )
                    )
                ).scalar_one_or_none()
                if stock is None or stock.quantity < 1:
                    raise ValueError(
                        f"Prodotto '{product.name}' esaurito in magazzino. "
                        "Ordinalo con order_product e avanza il tempo fino alla consegna."
                    )
                stock.quantity -= 1
                product_name = product.name
                # prodotto più efficace = trattamento più rapido
                duration_h = max(1, round(duration_h * max(0.4, 1.5 - product.efficacy)))

            description = (
                f"Trattamento {treatment_type} contro {disease.name} "
                + (f"con {product_name} " if product_name else "")
                + f"avviato sulla cella ({x},{y}), durata {duration_h}h simulate"
            )
            cell.status = "under_treatment"

        task = AgentTask(
            field_id=field.id,
            task_type=task_type,
            cell_x=x,
            cell_y=y,
            status="in_progress",
            started_at_sim=field.simulation_time,
            ends_at_sim=field.simulation_time + timedelta(hours=duration_h),
        )
        session.add(task)
        session.add(
            FieldEvent(
                field_id=field.id,
                event_type="treatment_started",
                cell_x=x,
                cell_y=y,
                description=description,
                sim_time=field.simulation_time,
            )
        )
        await session.flush()
        serialized = queries.serialize_task(task)
        names = await queries.disease_names_map(session)
        cell_snapshot = queries.serialize_cell(cell, names)
        sim_time = queries.iso(field.simulation_time)
        await session.commit()

    broker.publish(
        field_id, "task_started",
        {"task_id": serialized["id"], "x": x, "y": y, "ends_at_sim": serialized["ends_at_sim"]},
    )
    broker.publish(field_id, "field_update", {"cells": [cell_snapshot], "sim_time": sim_time})
    return serialized


@mcp.tool()
async def apply_diagnosis(
    field_id: str,
    x: int,
    y: int,
    disease_id: str,
    confidence: float | None = None,
    note: str = "",
) -> dict:
    """Registra sulla cella (x,y) la diagnosi di una malattia riconosciuta da una
    FOTO reale: imposta la malattia attiva (deve essere nel catalogo vite), porta
    la cella in stato 'diseased' e abilita il trattamento. Da usare dopo aver
    osservato i sintomi nell'immagine caricata dall'utente."""
    import uuid as _uuid

    try:
        did = _uuid.UUID(disease_id)
    except (ValueError, TypeError):
        raise ValueError(f"disease_id non valido: {disease_id!r}")

    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        cell = await queries.get_cell_or_error(session, field, x, y)
        disease = await session.get(DiseaseCatalog, did)
        if disease is None:
            raise ValueError(f"Malattia {disease_id} inesistente nel catalogo")

        cell.active_disease_id = disease.id
        cell.status = "diseased"
        cell.disease_risk_score = max(cell.disease_risk_score, 0.9)
        cell.last_inspected_at = field.simulation_time

        conf_txt = f" (confidenza {confidence:.0%})" if confidence is not None else ""
        description = f"Diagnosi da foto: {disease.name}{conf_txt} sulla cella ({x},{y})"
        if note:
            description += f" — {note}"
        session.add(
            FieldEvent(
                field_id=field.id,
                event_type="disease_detected",
                cell_x=x,
                cell_y=y,
                description=description,
                sim_time=field.simulation_time,
            )
        )
        names = await queries.disease_names_map(session)
        images = await queries.disease_image_map(session)
        snapshot = queries.serialize_cell(cell, names, images)
        sim_time = queries.iso(field.simulation_time)
        protocol = queries.serialize_disease(disease)
        await session.commit()

    broker.publish(field_id, "field_update", {"cells": [snapshot], "sim_time": sim_time})
    return {
        "cell": snapshot,
        "diagnosis": disease.name,
        "confidence": confidence,
        "recommended_action": protocol["recommended_action"],
        "treatment_duration_h": protocol["treatment_duration_h"],
        "hint": "Per curarla: verifica l'inventario (query_inventory), ordina se serve, poi start_treatment.",
    }

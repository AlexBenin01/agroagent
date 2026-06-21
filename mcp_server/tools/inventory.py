"""Tool MCP per l'inventario dei prodotti curativi e gli ordini.

L'agronomo AI ordina i prodotti dal catalogo: la consegna richiede un tempo
VARIABILE in ore SIMULATE (scalato dalla difficoltà del campo). L'ordine si
chiude e lo stock si aggiorna avanzando il tempo simulato (run_field_tick).
"""
import random
from datetime import timedelta

import queries
from db.session import SessionLocal
from field_engine import difficulty_profile
from mcp_app import mcp
from models import FieldEvent, ProductOrder
from sse import broker

MAX_ORDER_QUANTITY = 10


@mcp.tool()
async def query_inventory(field_id: str) -> dict:
    """Restituisce il catalogo dei prodotti curativi con lo stock disponibile
    nel campo e gli ordini in transito con la relativa ETA in ore simulate.
    Usalo prima di start_treatment per verificare di avere il prodotto adatto."""
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        return await queries.inventory_state(session, field)


@mcp.tool()
async def order_product(field_id: str, product_id: str, quantity: int = 1) -> dict:
    """Ordina un prodotto curativo dal catalogo. La consegna NON è immediata:
    arriva dopo un tempo variabile in ore simulate (tra delivery_min_h e
    delivery_max_h del prodotto, allungato dalla difficoltà). Avanza il tempo
    simulato per ricevere la consegna; poi lo stock sarà usabile da start_treatment."""
    if not 1 <= quantity <= MAX_ORDER_QUANTITY:
        raise ValueError(f"quantity deve essere tra 1 e {MAX_ORDER_QUANTITY}")
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        product = await queries.get_product_or_error(session, product_id)

        profile = difficulty_profile(field.difficulty)
        rng = random.Random()
        delivery_h = round(
            rng.uniform(product.delivery_min_h, product.delivery_max_h)
            * profile["delivery_mult"]
        )
        ordered_at = field.simulation_time
        arrives_at = ordered_at + timedelta(hours=delivery_h)

        order = ProductOrder(
            field_id=field.id,
            product_id=product.id,
            quantity=quantity,
            status="in_transit",
            ordered_at_sim=ordered_at,
            arrives_at_sim=arrives_at,
        )
        session.add(order)
        session.add(
            FieldEvent(
                field_id=field.id,
                event_type="product_ordered",
                description=(
                    f"Ordinati {quantity}x {product.name}; consegna prevista "
                    f"tra ~{delivery_h}h simulate"
                ),
                sim_time=ordered_at,
            )
        )
        await session.flush()
        result = {
            "order_id": str(order.id),
            "product_id": str(product.id),
            "product_name": product.name,
            "quantity": quantity,
            "delivery_hours": delivery_h,
            "ordered_at_sim": queries.iso(ordered_at),
            "arrives_at_sim": queries.iso(arrives_at),
        }
        await session.commit()

    broker.publish(field_id, "product_ordered", result)
    return result

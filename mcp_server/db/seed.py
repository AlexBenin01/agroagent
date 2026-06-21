"""Seed idempotente: catalogo malattie + campo demo al primo avvio.

Eseguito dall'entrypoint del container dopo `alembic upgrade head`:
    python -m db.seed
"""
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from db.session import SessionLocal
from field_factory import create_field
from models import DiseaseCatalog, Field, ProductCatalog

SEED_DATA_DIR = Path(__file__).parent / "seed_data"


async def seed_diseases(session) -> int:
    diseases = json.loads((SEED_DATA_DIR / "diseases.json").read_text(encoding="utf-8"))
    inserted = 0
    for entry in diseases:
        result = await session.execute(
            select(DiseaseCatalog).where(DiseaseCatalog.name == entry["name"])
        )
        if result.scalar_one_or_none() is None:
            session.add(DiseaseCatalog(**entry))
            inserted += 1
    return inserted


async def seed_products(session) -> int:
    products = json.loads((SEED_DATA_DIR / "products.json").read_text(encoding="utf-8"))
    inserted = 0
    for entry in products:
        result = await session.execute(
            select(ProductCatalog).where(ProductCatalog.name == entry["name"])
        )
        if result.scalar_one_or_none() is None:
            session.add(ProductCatalog(**entry))
            inserted += 1
    return inserted


async def seed_default_field(session) -> bool:
    result = await session.execute(select(Field).limit(1))
    if result.scalar_one_or_none() is not None:
        return False
    await create_field(session, name="Vigneto Demo")
    return True


async def main() -> None:
    async with SessionLocal() as session:
        inserted = await seed_diseases(session)
        products = await seed_products(session)
        await session.flush()
        created = await seed_default_field(session)
        await session.commit()
    print(
        f"[seed] malattie inserite: {inserted}; prodotti inseriti: {products}; "
        f"campo demo creato: {created}"
    )


if __name__ == "__main__":
    asyncio.run(main())

"""Engine e session factory async (psycopg3)."""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config

engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

"""Configurazione del MCP Server, interamente da variabili d'ambiente."""
import os

DATABASE_URL = os.environ["DATABASE_URL"]
MCP_AUTH_TOKEN = os.environ["MCP_AUTH_TOKEN"]
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

# Mapping tempo: a velocità ×1, 1 giorno simulato dura SIM_DAY_REAL_MINUTES minuti
# reali. Il tick avanza SIM_HOURS_PER_TICK ore simulate per campo (granularità);
# l'intervallo reale fra i tick è derivato perché 24h coprano un giorno reale.
SIM_DAY_REAL_MINUTES = float(os.getenv("SIM_DAY_REAL_MINUTES", "5"))
SIM_HOURS_PER_TICK = int(os.getenv("SIM_HOURS_PER_TICK", "1"))
TICK_INTERVAL_SECONDS = SIM_DAY_REAL_MINUTES * 60 * SIM_HOURS_PER_TICK / 24

DEFAULT_FIELD_ROWS = int(os.getenv("DEFAULT_FIELD_ROWS", "10"))
DEFAULT_FIELD_COLS = int(os.getenv("DEFAULT_FIELD_COLS", "10"))
IMAGE_BASE_PATH = os.getenv("IMAGE_BASE_PATH", "/app/data/images")
# Foto reali caricate dal contadino: storage scrivibile e DURATURO (bind su host)
UPLOAD_BASE_PATH = os.getenv("UPLOAD_BASE_PATH", "/app/uploads")

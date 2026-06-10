"""Configurazione del MCP Server, interamente da variabili d'ambiente."""
import os

DATABASE_URL = os.environ["DATABASE_URL"]
MCP_AUTH_TOKEN = os.environ["MCP_AUTH_TOKEN"]
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
FIELD_TICK_INTERVAL_MINUTES = int(os.getenv("FIELD_TICK_INTERVAL_MINUTES", "5"))
DEFAULT_FIELD_ROWS = int(os.getenv("DEFAULT_FIELD_ROWS", "10"))
DEFAULT_FIELD_COLS = int(os.getenv("DEFAULT_FIELD_COLS", "10"))
IMAGE_BASE_PATH = os.getenv("IMAGE_BASE_PATH", "/app/data/images")

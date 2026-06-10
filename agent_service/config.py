"""Configurazione dell'Agent Service, interamente da variabili d'ambiente."""
import os

OPENAI_BASE_URL = os.environ["OPENAI_BASE_URL"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
LLM_MODEL = os.environ["LLM_MODEL"]
MCP_SERVER_URL = os.environ["MCP_SERVER_URL"]
MCP_AUTH_TOKEN = os.environ["MCP_AUTH_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

# Tetto del loop ReAct: ~15 iterazioni (ogni iterazione = 1 nodo LLM + 1 nodo tool)
MAX_AGENT_ITERATIONS = 15
LLM_TIMEOUT_SECONDS = 180  # prima inferenza vLLM lenta (warm-up)
HISTORY_MAX_MESSAGES = 30

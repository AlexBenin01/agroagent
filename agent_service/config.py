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

# Disattiva il "thinking" dei modelli Qwen3 (blocchi <think>…</think>): riduce
# molto la latenza e i token sprecati. Per i modelli che non lo supportano,
# l'opzione viene semplicemente ignorata dal server.
LLM_ENABLE_THINKING = os.getenv("LLM_ENABLE_THINKING", "false").lower() in ("1", "true", "yes")

# Memoria: soglia di token oltre la quale i turni vecchi vengono riassunti
CONTEXT_MAX_TOKENS = int(os.getenv("CONTEXT_MAX_TOKENS", "8000"))

# DSN psycopg per checkpointer/store LangGraph (senza il prefisso SQLAlchemy)
PG_DSN = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

# Embeddings opzionali per la ricerca semantica nello Store a lungo termine
EMBEDDINGS_BASE_URL = os.getenv("EMBEDDINGS_BASE_URL") or ""
EMBEDDINGS_API_KEY = os.getenv("EMBEDDINGS_API_KEY") or ""
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL") or ""
EMBEDDINGS_DIMS = int(os.getenv("EMBEDDINGS_DIMS", "1536"))

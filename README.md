# 🌿 AgroAgent

**An AI agronomist agent supervising a simulated vineyard — built on MCP, LangGraph and FastAPI.**

AgroAgent is a web-based agricultural simulation supervised by an AI agent. The user
watches a vineyard as a 10×10 grid on a 2D map while an AI agent — driven through a
chat panel — moves across the field, reads simulated sensors, takes simulated drone
photos, creates checkpoints, launches asynchronous treatments and explains in natural
language what is happening and why.

> **Status:** MVP complete — all 5 sprints implemented and smoke-tested.
> The full technical plan lives in [`agroagent_piano_tecnico.md`](agroagent_piano_tecnico.md).

---

## How it works

The field state lives as a **single source of truth on a remote MCP server**
(Model Context Protocol, Streamable HTTP transport). The agent never touches the
database directly: it observes and acts on the field exclusively through 10 MCP tools.
The browser receives real-time field updates over SSE.

```
Browser (Canvas + Chat) ◀──SSE── MCP Server (FastAPI + FastMCP) ──▶ PostgreSQL
                                        ▲
                                        │ MCP (Streamable HTTP + bearer auth)
                            Agent Service (LangGraph ReAct)
                                        │
                                        ▼ OpenAI-compatible API
                            LLM endpoint (Qwen3 on vLLM / Ollama / any /v1)
```

### Key design decisions

- **Simulated clock, not wall clock.** Treatments last *simulation hours*; the field
  engine closes tasks by comparing `sim_time` against `ends_at_sim`. No job queue,
  no real-time timers — advancing simulated time by 72h completes a 72h treatment
  instantly, as it should.
- **MCP done properly.** Official Python SDK (FastMCP), Streamable HTTP transport,
  bearer-token authentication between services. No hand-rolled JSON-RPC.
- **LLM-agnostic by construction.** The agent talks to any OpenAI-compatible
  endpoint via three environment variables (`OPENAI_BASE_URL`, `OPENAI_API_KEY`,
  `LLM_MODEL`). Reference setup: Qwen3 served by vLLM on a Colab A100, exposed
  through an HTTPS tunnel. Ollama or any cloud provider works the same way.
- **Security baseline from day one.** No hardcoded credentials, Postgres not
  exposed on the host, explicit CORS allowlist, server-side validation of every
  tool parameter, capped agent loop, static files served safely.

## Getting started

Prerequisites: Docker Desktop, Python 3.11+ (only for the one-off image script).

```bash
# 1. configuration — fill in POSTGRES_PASSWORD, MCP_AUTH_TOKEN and the LLM endpoint
cp .env.example .env

# 2. placeholder plant photos (replace later with a PlantVillage subset if you wish)
pip install pillow
python scripts/generate_placeholder_images.py

# 3. run everything (postgres + migrations + seed happen automatically)
docker compose up --build

# 4. open the app
# http://localhost:3000
```

On first start the MCP server applies the Alembic migrations, seeds the 5 vine
disease catalog and creates a demo field with an active downy-mildew outbreak.

### Pointing the agent at an LLM

Any OpenAI-compatible endpoint with **tool calling** works. In `.env`:

| Setup | `OPENAI_BASE_URL` | `LLM_MODEL` |
|---|---|---|
| vLLM on Colab (reference) | `https://<tunnel>.trycloudflare.com/v1` | `Qwen/Qwen3-32B` |
| Ollama on the host | `http://host.docker.internal:11434/v1` | e.g. `qwen3:8b` |
| Cloud provider | provider `/v1` URL | provider model id |

For the Colab/vLLM reference setup (including `--enable-auto-tool-choice
--tool-call-parser hermes`) see the [technical plan](agroagent_piano_tecnico.md#llm--qwen3-servito-da-vllm-su-google-colab).
After changing `.env`, restart just the agent: `docker compose up -d agent_service`.

### Try the demo flow

In the chat panel:

1. *«Com'è la situazione del campo?»* — the agent reads the full field state
2. *«Ispeziona la zona malata»* — focus box moves, a simulated drone photo appears
3. *«Che malattia è? Come la curiamo?»* — diagnosis against the disease catalog
4. *«Avvia il trattamento»* — a treatment task starts (duration in simulated hours)
5. *«Avanza il tempo di 72 ore»* — the clock jumps, the task completes, the cell turns light green

### Smoke tests

```bash
docker compose cp scripts/sprint2_smoke_test.py mcp_server:/app/t.py && docker compose exec mcp_server python /app/t.py
docker compose cp scripts/sse_smoke_test.py mcp_server:/app/s.py && docker compose exec mcp_server python /app/s.py
```

## Simulation scope (MVP)

| Aspect | Choice |
|---|---|
| Crop | Grapevine (*Vitis vinifera*) |
| Field | 10×10 grid, 100 m² per cell |
| Diseases | Downy mildew, powdery mildew, grey mould, flavescence dorée, phomopsis |
| Sensors per cell | Soil moisture, soil temperature, nutrient index |
| Weather | Daily rainfall, humidity, temperature, 7-day forecast |
| Photos | Simulated — placeholder images out of the box; PlantVillage subset (CC BY 4.0) recommended |

## MCP tools exposed to the agent

`get_field_state` · `get_cell_detail` · `capture_field_photo` · `get_weather_summary` ·
`move_focus_area` · `create_checkpoint` · `start_treatment` · `advance_simulation_time` ·
`query_disease_catalog` · `get_care_protocol`

## Stack

**Backend:** Python, FastAPI, MCP Python SDK (FastMCP), LangGraph, SQLAlchemy + Alembic, PostgreSQL
**Frontend:** Vanilla JS (ES modules), Canvas 2D, Server-Sent Events
**Infra:** Docker Compose (postgres, mcp_server, agent_service, frontend)
**LLM:** any OpenAI-compatible endpoint — reference: Qwen3 on vLLM (Colab A100)

## Roadmap

- [x] Technical design & security review
- [x] Sprint 1 — Foundation: Compose, DB schema, migrations, seed data, first MCP tools
- [x] Sprint 2 — Simulation engine: weather ticks, disease spread, simulated-time tasks, SSE
- [x] Sprint 3 — LangGraph agent: MCP client, ReAct graph, chat endpoint
- [x] Sprint 4 — UI: canvas grid, focus box, sensor panel, chat
- [x] Sprint 5 — Polish: timeline, inline photos, full demo flow
- [ ] Next: real PlantVillage images, OAuth 2.1 on `/mcp` if ever exposed, computer-vision diagnosis (v2)

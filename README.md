# 🌿 AgroAgent

**An AI agronomist agent supervising a simulated vineyard — built on MCP, LangGraph and FastAPI.**

AgroAgent is a web-based agricultural simulation supervised by an AI agent. The user
watches a vineyard as a 10×10 grid on a 2D map while an AI agent — driven through a
chat panel — moves across the field, reads simulated sensors, takes simulated drone
photos, creates checkpoints, launches asynchronous treatments and explains in natural
language what is happening and why.

## ✨ Highlights

- 🧠 **Agentic core** — a LangGraph **ReAct** agent acts on the world only through **MCP tools** (13 of them), never touching the database directly.
- 👁️ **Multimodal diagnosis** — a farmer uploads a real leaf photo; the model *sees* it, recognizes the vine disease and updates the field.
- 💾 **Persistent memory** — LangGraph Postgres **checkpointer + store** (optional pgvector semantic search) with automatic context summarization to tame the context window.
- 🕒 **Real-time simulation** — disease spreads by weather & contagion; **1 simulated day = 5 real minutes**, with ×1–×4 speed and Normal/Hard/Apocalypse modes.
- 📊 **LLM observability** — token-by-token streaming with a live panel: time-to-first-token, time-to-first-tool, tokens/s.
- 🔌 **Model-agnostic** — any OpenAI-compatible endpoint (Qwen3 on vLLM, Ollama, or a cloud provider).

---

## How it works

The field state lives as a **single source of truth on a remote MCP server**
(Model Context Protocol, Streamable HTTP transport). The agent never touches the
database directly: it observes and acts on the field exclusively through 13 MCP tools.
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

On first start the MCP server applies the Alembic migrations, seeds the disease
catalog (PlantVillage grape classes) plus the curative-product catalog, and
creates a demo field with an active outbreak. From the start screen you pick a
**game mode** (Normal / Hard / Apocalypse) that scales disease spread, recovery
and delivery times.

### Pointing the agent at an LLM

Any OpenAI-compatible endpoint with **tool calling** works. In `.env`:

| Setup | `OPENAI_BASE_URL` | `LLM_MODEL` |
|---|---|---|
| vLLM on Colab (reference) | `https://<tunnel>.trycloudflare.com/v1` | `Qwen/Qwen3-32B` |
| llama.cpp on Colab (Qwen3.6, 40 GB A100) | `https://<tunnel>.trycloudflare.com/v1` | `qwen3.6-35b-a3b` |
| Ollama on the host | `http://host.docker.internal:11434/v1` | e.g. `qwen3:8b` |
| Cloud provider | provider `/v1` URL | provider model id |

vLLM needs tool calling enabled (`--enable-auto-tool-choice --tool-call-parser hermes`),
and a **multimodal** model (e.g. a Qwen-VL variant) for the photo-diagnosis flow.
For serving Qwen3.6-35B-A3B (GGUF) on a 40 GB A100 via llama.cpp, open the
ready-to-run notebook [colab/agroagent_llm.ipynb](colab/agroagent_llm.ipynb).
After changing `.env`, restart just the agent: `docker compose up -d agent_service`.
On Qwen3 the agent disables the hidden `<think>` reasoning (`LLM_ENABLE_THINKING=false`)
for much lower latency.

### Try the demo flow

In the chat panel:

1. *«Com'è la situazione del campo?»* — the agent reads the full field state
2. *«Ispeziona la zona malata»* — focus box moves, a simulated drone photo appears
3. *«Che malattia è? Come la curiamo?»* — diagnosis against the disease catalog
4. *«Ordina il prodotto adatto e curala»* — the agent checks the inventory,
   orders a product (variable simulated delivery time), waits for delivery, then
   starts the treatment
5. *«Avanza il tempo di 72 ore»* — the clock jumps, the task completes, the cell turns light green

The agent reply streams **token by token**, and a live **observability panel**
shows per-turn `ttft_ms` (time-to-first-token), `ttftool_ms` (time-to-first-tool)
and tokens/s — also logged in the `agent_service` logs. The header
**×1/×2/×3/×4 / ⏸** control sets the real-time speed at which the simulated clock
auto-advances — at **×1 one simulated day lasts 5 real minutes**
(`SIM_DAY_REAL_MINUTES` in `.env`); ×k multiplies it.

### Memory / knowledge base

Memory uses the **native LangGraph persistence layer** (the current documented
approach):

- **Short-term (per conversation)** — a **Postgres checkpointer**
  (`AsyncPostgresSaver`) keyed by `thread_id` = chat session. History is restored
  on reload and never re-sent by hand.
- **Context window** — a `langmem` **`SummarizationNode`** runs as the
  `pre_model_hook`, summarizing old turns above `CONTEXT_MAX_TOKENS`. Together
  with a compact `get_field_state` (summary instead of all 100 cells) this fixes
  the previous *"Context size exceeded"* errors.
- **Long-term (cross-session)** — a **Postgres Store** (`AsyncPostgresStore`,
  namespace `("agroagent", <field_id>, "memories")`) exposed to the agent via
  `manage_memory` / `search_memory` tools, so it remembers facts across sessions.
- **Semantic search** (optional) — set `EMBEDDINGS_BASE_URL` / `EMBEDDINGS_MODEL`
  / `EMBEDDINGS_DIMS` in `.env` to an OpenAI-compatible embeddings endpoint; the
  Store then indexes memories with **pgvector** (the Postgres image is
  `pgvector/pgvector:pg16`). Leave them empty to keep long-term memory without
  semantic search. The checkpointer/store tables are created automatically at
  startup (not via Alembic).

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
| Diseases | PlantVillage grape classes: Black Rot, Esca (Black Measles), Leaf Blight |
| Sensors per cell | Soil moisture, soil temperature, nutrient index |
| Weather | Daily rainfall, humidity, temperature, 7-day forecast |
| Photos | Simulated — placeholder images out of the box; PlantVillage subset (CC BY 4.0) recommended |
| Game modes | Normal / Hard / Apocalypse (disease spread, recovery, delivery scaling) |
| Inventory | Curative products ordered by the agent, with variable simulated delivery time |

## Image dataset (PlantVillage)

The placeholder generator writes light synthetic images under
`data/images/{healthy,diseased/<class>}`. To use realistic photos, drop a subset
of the **PlantVillage** grape classes into the same folders (the app serves
whatever is there):

```bash
# Kaggle CLI (needs a kaggle.json token)
kaggle datasets download -d vipoooool/new-plant-diseases-dataset
# from the archive, copy ~10–20 images per class into:
#   data/images/diseased/black_rot/     <- Grape___Black_rot
#   data/images/diseased/esca/          <- Grape___Esca_(Black_Measles)
#   data/images/diseased/leaf_blight/   <- Grape___Leaf_blight_(Isariopsis_Leaf_Spot)
#   data/images/healthy/                <- Grape___healthy
```

Any `.jpg/.jpeg/.png` works; `capture_field_photo` picks one at random per cell,
and a representative image per disease is shown in the sensor panel when you
click a diseased cell (even before any photo is taken).

**Lab vs field — important.** PlantVillage images are shot in a **lab** (uniform
background). A farmer's real photo is **in the field** with a complex background,
so models/recognition tuned only on PlantVillage are over-optimistic on real
photos. For realistic testing of the upload-and-recognize flow, also grab
**in-the-wild** datasets:
- **PlantDoc** — real-field, annotated: https://github.com/pratikkayal/PlantDoc-Dataset
- **PlantWild / PlantSeg** — large in-the-wild sets (papers linked in the plan)
- **Roboflow Universe** — search "grapevine disease" / "grape leaf disease"

### Photo upload & vision diagnosis

A farmer can **upload a real photo** of a plant: click a cell, attach a photo
with the 📷 button in chat, and ask *"che malattia è?"*. The (multimodal) model
looks at the image, identifies the vine disease, and calls `apply_diagnosis` to
set the disease on that cell — then the normal inventory/treatment flow applies.
Uploaded photos are stored **durably** on the host under `./uploads/` (bind
mount, survives `docker compose down -v`) and served from `/uploads`. Requires a
multimodal LLM endpoint that supports the OpenAI `image_url` format.

## MCP tools exposed to the agent

`get_field_state` · `get_cell_detail` · `capture_field_photo` · `get_weather_summary` ·
`move_focus_area` · `create_checkpoint` · `start_treatment` · `advance_simulation_time` ·
`query_disease_catalog` · `get_care_protocol` · `query_inventory` · `order_product` ·
`apply_diagnosis`

## Stack

**Backend:** Python, FastAPI, MCP Python SDK (FastMCP), LangGraph (+ langmem), SQLAlchemy + Alembic, PostgreSQL + pgvector
**Frontend:** Vanilla JS (ES modules), Canvas 2D, Server-Sent Events
**Infra:** Docker Compose (postgres, mcp_server, agent_service, frontend)
**LLM:** any OpenAI-compatible endpoint — reference: multimodal Qwen3 on vLLM (Colab A100)

## Roadmap

- [x] Technical design & security review
- [x] Sprint 1 — Foundation: Compose, DB schema, migrations, seed data, first MCP tools
- [x] Sprint 2 — Simulation engine: weather ticks, disease spread, simulated-time tasks, SSE
- [x] Sprint 3 — LangGraph agent: MCP client, ReAct graph, chat endpoint
- [x] Sprint 4 — UI: canvas grid, focus box, sensor panel, chat
- [x] Sprint 5 — Polish: timeline, inline photos, full demo flow
- [x] Sprint 6 — Gameplay: game modes, agent-managed inventory with variable
  deliveries, ×2/×3/×4 real-time accelerator, token-by-token streaming with
  TTFToken/TTFtool metrics, PlantVillage-aligned disease catalog
- [x] Sprint 7 — Memory & time: LangGraph persistence (Postgres checkpointer +
  Store), langmem summarization + compact tool outputs (fixes context overflow),
  optional pgvector semantic memory, real-time clock (1 sim day = 5 real min),
  quieter MCP logs
- [x] Sprint 8 — Photo diagnosis & observability: farmer uploads a real photo
  (durable host storage), multimodal agent recognizes the vine disease and applies
  it to the cell (`apply_diagnosis`), disease reference image on cell click; live
  LLM observability panel (TTFToken/TTFtool/tokens-per-sec); Qwen3 thinking disabled
  for ~70× lower latency
- [ ] Next: end-of-season scoring & budget economy, OAuth 2.1 on `/mcp` if ever
  exposed, in-field fine-tuned classifier as a fallback to the multimodal model

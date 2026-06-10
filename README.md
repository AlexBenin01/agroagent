# 🌿 AgroAgent

**An AI agronomist agent supervising a simulated vineyard — built on MCP, LangGraph and FastAPI.**

AgroAgent is a web-based agricultural simulation supervised by an AI agent. The user
watches a vineyard as a 10×10 grid on a 2D map while an AI agent — driven through a
chat panel — moves across the field, reads simulated sensors, takes simulated drone
photos, creates checkpoints, launches asynchronous treatments and explains in natural
language what is happening and why.

> **Status:** design complete, implementation in progress (Sprint 1).
> The full technical plan lives in [`agroagent_piano_tecnico.md`](agroagent_piano_tecnico.md).

---

## How it works

The field state lives as a **single source of truth on a remote MCP server**
(Model Context Protocol, Streamable HTTP transport). The agent never touches the
database directly: it observes and acts on the field exclusively through MCP tools.
The browser receives real-time field updates over SSE.

```
Browser (Canvas + Chat) ──SSE──▶ MCP Server (FastAPI + FastMCP) ──▶ PostgreSQL
                                        ▲
                                        │ MCP (Streamable HTTP + bearer auth)
                            Agent Service (LangGraph ReAct)
                                        │
                                        ▼ OpenAI-compatible API
                            LLM endpoint (Qwen3 on vLLM / any /v1)
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

## Simulation scope (MVP)

| Aspect | Choice |
|---|---|
| Crop | Grapevine (*Vitis vinifera*) |
| Field | 10×10 grid, 100 m² per cell |
| Diseases | Downy mildew, powdery mildew, grey mould, flavescence dorée, phomopsis |
| Sensors per cell | Soil moisture, soil temperature, nutrient index |
| Weather | Daily rainfall, humidity, temperature, 7-day forecast |
| Photos | Simulated — images drawn from the PlantVillage dataset (CC BY 4.0) |

## Stack

**Backend:** Python, FastAPI, MCP Python SDK (FastMCP), LangGraph, SQLAlchemy + Alembic, PostgreSQL
**Frontend:** Vanilla JS / Alpine.js, Canvas 2D, Server-Sent Events
**Infra:** Docker Compose (postgres, mcp_server, agent_service, frontend)
**LLM:** any OpenAI-compatible endpoint — reference: Qwen3 on vLLM (Colab A100)

## Getting started

```bash
cp .env.example .env   # fill in credentials and the LLM endpoint
docker compose up --build
# open http://localhost:3000
```

See the [technical plan](agroagent_piano_tecnico.md) for the full architecture,
database schema, MCP tool definitions, simulation engine rules and sprint roadmap.

## Roadmap

- [x] Technical design & security review
- [ ] Sprint 1 — Foundation: Compose, DB schema, migrations, seed data, first MCP tools
- [ ] Sprint 2 — Simulation engine: weather ticks, disease spread, simulated-time tasks, SSE
- [ ] Sprint 3 — LangGraph agent: MCP client, ReAct graph, chat endpoint
- [ ] Sprint 4 — UI: canvas grid, focus box, sensor panel, chat
- [ ] Sprint 5 — Polish: timeline, inline photos, full demo flow

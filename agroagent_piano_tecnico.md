# AgroAgent — Piano d'Azione Tecnico per Claude Code

## Obiettivo del Progetto

Costruire una web app di simulazione agricola supervisionata da un agente AI.
L'utente vede un campo diviso in celle su una mappa 2D. Un agente AI — controllabile
via chat — si sposta sul campo, legge sensori simulati, scatta foto simulate, crea
checkpoint, lancia interventi asincroni (cura piante malate, irrigazione) e spiega
in linguaggio naturale cosa sta succedendo.

Il campo vive come **source of truth su un server MCP remoto**. Il server aggiorna
il client con lo stato corrente del campo tramite polling/SSE. L'agente usa i tool
MCP per osservare e modificare il campo.

---

## Scope MVP — Vincoli precisi

- **Coltura iniziale:** Vite (Vitis vinifera)
- **Malattie simulate:** 5 (Peronospora, Oidio, Botrite, Flavescenza Dorata, Escoriosi)
- **Campo:** griglia 10×10 celle, ogni cella = 100m²
- **Sensori per cella:** soil_moisture, soil_temperature, nutrient_index (simulati)
- **Meteo:** pioggia giornaliera, umidità aria, temperatura, previsione 7 giorni (simulato)
- **Azioni agente:** osserva cella, scatta foto simulata, crea checkpoint, avvia cura, avanza tempo
- **UI:** 2D grid canvas + pannello chat + pannello sensori + timeline eventi
- **No computer vision reale in v1:** foto simulate = immagini selezionate da dataset

---

## Stack Tecnologico

```
Backend (Python)
├── FastAPI                     — API HTTP + SSE per aggiornamenti campo
├── MCP Python SDK (FastMCP)    — MCP server remoto (transport Streamable HTTP) + MCP client
├── LangGraph                   — Orchestrazione agente (ReAct loop)
├── LLM OpenAI-compatible       — Qwen3 servito da vLLM su Colab (A100), via API /v1
├── PostgreSQL                  — Stato campo, meteo, knowledge base, task
└── SQLAlchemy + Alembic        — ORM e migrazioni

Frontend
├── HTML + Vanilla JS / Alpine.js   — Semplicità e velocità demo
├── Canvas 2D                        — Rendering griglia campo
└── SSE EventSource                  — Aggiornamenti real-time dal server

Storage
└── Local filesystem                 — Immagini piante (dataset + snapshot simulati)

Infrastruttura
└── Docker Compose                   — postgres + mcp_server + agent_service + frontend
```

### Decisioni architetturali (revisione PM)

1. **Niente Celery/Redis.** `treatment_duration_h` è espresso in **ore di simulazione**,
   non in tempo reale: un timer Celery (tempo reale) sarebbe incoerente con l'orologio
   simulato — se l'utente avanza il tempo di 72h, il trattamento deve completarsi
   immediatamente. La chiusura dei task viene quindi calcolata dal `field_engine`
   a ogni tick confrontando `sim_time` con `ends_at_sim`. Il tick di background
   (ogni N minuti reali) è un task `asyncio` dentro il processo MCP Server.
   Risultato: 2 container in meno, zero code da gestire, semantica del tempo coerente.
2. **MCP su Streamable HTTP.** Si usa l'SDK Python ufficiale `mcp` (FastMCP) montato
   nell'app FastAPI: niente JSON-RPC implementato a mano. Il transport Streamable HTTP
   è quello raccomandato dalla spec MCP corrente per server remoti (il vecchio
   transport HTTP+SSE per MCP è deprecato; l'SSE resta solo per gli aggiornamenti
   campo → browser, che è un uso corretto e separato).
3. **Tempo reale verso il client: SSE, non WebSocket.** Il flusso è unidirezionale
   (server → client); SSE è lo strumento giusto, con heartbeat periodico e
   riconnessione automatica di `EventSource`.
4. **LLM disaccoppiato via API OpenAI-compatible.** L'Agent Service non dipende
   da un provider: usa `ChatOpenAI` di langchain-openai con `base_url`, `api_key`
   e `model` da variabili d'ambiente. In questo progetto l'endpoint è vLLM su
   Google Colab (GPU A100) esposto tramite tunnel HTTPS; lo stack applicativo
   resta interamente su Docker, l'LLM è solo un URL nel `.env`. Qualsiasi altro
   endpoint compatibile (Ollama locale, LM Studio, provider cloud) funziona
   cambiando tre variabili.

---

## Architettura dei Servizi

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Compose                        │
│                                                         │
│  ┌──────────────────────┐     ┌──────────────┐          │
│  │  MCP Server          │◄────│  Agent Svc   │          │
│  │  (FastAPI + FastMCP) │ MCP │  (LangGraph) │          │
│  │  :8001               │ st. │  :8002       │          │
│  │  + tick asyncio      │ HTTP└──────┬───────┘          │
│  └──────┬───────────────┘            │                  │
│         │ campo, meteo, task         │ chat_sessions    │
│         ▼                            ▼                  │
│  ┌──────────────────────────────────┐                   │
│  │         PostgreSQL (no porta host)│                  │
│  │  campo | meteo | malattie |      │                   │
│  │  task  | eventi | sessioni chat  │                   │
│  └──────────────────────────────────┘                   │
│                                                         │
│  ┌─────────────────────┐                                │
│  │  Web Client (nginx) │                                │
│  │  :3000              │                                │
│  │  Canvas + Chat + SSE│                                │
│  └─────────────────────┘                                │
└─────────────────────────────────────────────────────────┘
```

Il **MCP Server** è il solo servizio che legge e scrive lo **stato del campo** su Postgres
(celle, meteo, malattie, task, eventi). Esegue anche il tick di simulazione in background.
L'**Agent Service** non accede mai alle tabelle del campo: usa esclusivamente i tool MCP
(autenticati con bearer token). Accede a Postgres solo per la propria tabella `chat_sessions`.
Il **Web Client** consuma SSE dal MCP Server per aggiornamenti real-time della mappa.
Postgres non espone porte sull'host: è raggiungibile solo dalla rete interna Compose.
L'**LLM è fuori dal Compose**: l'Agent Service lo raggiunge in HTTPS all'endpoint
OpenAI-compatible indicato da `OPENAI_BASE_URL` (vLLM su Colab via tunnel).

---

## Struttura del Progetto

Il progetto vive nella root del repository `Hay_simulator/` (nessuna sottocartella
`agroagent/` annidata).

```
Hay_simulator/
├── docker-compose.yml
├── .env.example                 # template; il .env reale è in .gitignore
├── .gitignore
│
├── mcp_server/
│   ├── Dockerfile
│   ├── main.py                  # FastAPI app + mount FastMCP + SSE endpoint + tick asyncio
│   ├── field_engine.py          # Motore di simulazione: tick, meteo, malattie, chiusura task
│   ├── auth.py                  # Verifica bearer token sulle richieste MCP
│   ├── tools/
│   │   ├── observe.py           # get_field_state, move_focus, capture_photo
│   │   ├── actions.py           # create_checkpoint, start_treatment, irrigate
│   │   ├── weather.py           # get_weather_summary, advance_time
│   │   └── knowledge.py        # query_disease_catalog, get_care_protocol
│   ├── models/                  # SQLAlchemy models
│   └── db/
│       ├── migrations/          # Alembic
│       └── seed_data/           # JSON seed: malattie, foto, regole
│
├── agent_service/
│   ├── Dockerfile
│   ├── main.py                  # FastAPI: /chat endpoint
│   ├── agent.py                 # LangGraph ReAct graph
│   ├── mcp_client.py            # MCP client (streamable HTTP + bearer token)
│   ├── tools_registry.py       # Bind tool MCP → LangGraph tools
│   └── prompts/
│       └── system_prompt.txt   # Prompt sistema agronomo
│
├── frontend/
│   ├── index.html
│   ├── js/
│   │   ├── field_canvas.js      # Canvas rendering 10x10 grid
│   │   ├── agent_focus.js       # Box mobile dell'area supervisionata
│   │   ├── checkpoints.js       # Layer checkpoint sulla mappa
│   │   ├── chat.js              # Pannello chat
│   │   ├── sensors_panel.js    # Pannello sensori cella selezionata
│   │   ├── timeline.js          # Storico eventi campo
│   │   └── sse_client.js       # EventSource → aggiornamento canvas
│   └── css/
│       └── style.css
│
└── data/
    └── images/                  # Foto dataset (PlantVillage subset)
        ├── healthy/
        └── diseased/
            ├── peronospora/
            ├── oidio/
            ├── botrite/
            ├── flavescenza/
            └── escoriosi/
```

---

## Schema Database

### Tabella: `fields`
```sql
id              UUID PRIMARY KEY
name            TEXT
rows            INT DEFAULT 10
cols            INT DEFAULT 10
crop_type       TEXT DEFAULT 'vite'
created_at      TIMESTAMPTZ
simulation_time TIMESTAMPTZ          -- orologio simulato del campo
```

### Tabella: `field_cells`
```sql
id                  UUID PRIMARY KEY
field_id            UUID REFERENCES fields
x                   INT               -- colonna 0-9
y                   INT               -- riga 0-9
soil_moisture       FLOAT             -- 0.0-1.0
soil_temperature    FLOAT             -- °C
nutrient_index      FLOAT             -- 0.0-1.0
health_score        FLOAT             -- 0.0-1.0
disease_risk_score  FLOAT             -- 0.0-1.0
active_disease_id   UUID REFERENCES disease_catalog NULLABLE
status              TEXT              -- healthy | at_risk | diseased | under_treatment | treated
last_inspected_at   TIMESTAMPTZ
last_photo_path     TEXT
updated_at          TIMESTAMPTZ

UNIQUE (field_id, x, y)
```

### Tabella: `weather_daily`
```sql
id              UUID PRIMARY KEY
field_id        UUID REFERENCES fields
sim_date        DATE
rainfall_mm     FLOAT
humidity_pct    FLOAT
temp_min        FLOAT
temp_max        FLOAT
is_forecast     BOOL DEFAULT FALSE
created_at      TIMESTAMPTZ

UNIQUE (field_id, sim_date, is_forecast)
```

### Tabella: `disease_catalog`
```sql
id                      UUID PRIMARY KEY
name                    TEXT              -- es. "Peronospora della vite"
pathogen_type           TEXT              -- fungus | bacteria | virus | insect
crop_type               TEXT
symptoms_visible        TEXT[]            -- es. ["macchie oleose foglia", "peluria bianca"]
favorable_temp_min      FLOAT
favorable_temp_max      FLOAT
favorable_humidity_min  FLOAT
spread_speed            TEXT              -- slow | medium | fast
severity_score          INT               -- 1-5
treatment_duration_h    INT               -- ore simulazione
recommended_action      TEXT
image_folder            TEXT              -- path in data/images/diseased/
```

### Tabella: `checkpoints`
```sql
id              UUID PRIMARY KEY
field_id        UUID REFERENCES fields
cell_x          INT
cell_y          INT
type            TEXT    -- disease_found | high_moisture | treatment_done | inspection
note            TEXT
created_at      TIMESTAMPTZ
created_by      TEXT    -- 'agent' | 'user'
resolved        BOOL DEFAULT FALSE
```

### Tabella: `agent_tasks`

I timestamp dei task sono nell'**orologio simulato** del campo, non in tempo reale:
il `field_engine` chiude un task quando `sim_time >= ends_at_sim`.

```sql
id              UUID PRIMARY KEY
field_id        UUID REFERENCES fields
task_type       TEXT    -- treatment | irrigation | inspection
cell_x          INT
cell_y          INT
status          TEXT    -- in_progress | completed | failed
started_at_sim  TIMESTAMPTZ   -- sim_time di avvio
ends_at_sim     TIMESTAMPTZ   -- started_at_sim + treatment_duration_h
completed_at_sim TIMESTAMPTZ
result_note     TEXT
created_at      TIMESTAMPTZ   -- tempo reale, solo per audit
```

### Tabella: `field_events`
```sql
id              UUID PRIMARY KEY
field_id        UUID REFERENCES fields
event_type      TEXT    -- disease_detected | treatment_started | rain | inspection | time_advance
cell_x          INT NULLABLE
cell_y          INT NULLABLE
description     TEXT
sim_time        TIMESTAMPTZ
created_at      TIMESTAMPTZ
```

### Tabella: `chat_sessions`
```sql
id              UUID PRIMARY KEY
field_id        UUID REFERENCES fields
messages        JSONB   -- array LangGraph message history
created_at      TIMESTAMPTZ
updated_at      TIMESTAMPTZ
```

---

## MCP Tool Definitions

Il MCP Server espone questi tool tramite FastMCP (SDK ufficiale `mcp`), transport
**Streamable HTTP**, montato nell'app FastAPI su `/mcp`. Ogni tool è una funzione
Python decorata con `@mcp.tool()`.

Regole comuni a tutti i tool (validazione server-side, mai fidarsi del chiamante):
- `field_id` deve esistere, altrimenti errore esplicito (no creazione implicita)
- `x`, `y` validati nei bounds della griglia del campo (0..cols-1, 0..rows-1)
- `hours` di `advance_simulation_time` limitato a 1–720
- i parametri enum (`checkpoint_type`, `treatment_type`) usano `Literal[...]`
  così lo schema JSON pubblicato al client MCP vincola già i valori ammessi

### Tool di Osservazione

```python
@mcp.tool()
async def get_field_state(field_id: str) -> dict:
    """
    Restituisce lo stato completo del campo: griglia celle,
    meteo corrente, task attivi, checkpoints aperti.
    """

@mcp.tool()
async def get_cell_detail(field_id: str, x: int, y: int) -> dict:
    """
    Restituisce dettaglio completo di una singola cella:
    sensori, malattia attiva, storico eventi, foto recenti.
    """

@mcp.tool()
async def capture_field_photo(field_id: str, x: int, y: int) -> dict:
    """
    Simula scatto fotografico dell'area. Seleziona un'immagine
    rappresentativa dallo stato attuale della cella (healthy o
    diseased/{disease_name}) e la registra nel DB.
    Restituisce path immagine e metadati.
    """

@mcp.tool()
async def get_weather_summary(field_id: str, days_back: int = 7) -> dict:
    """
    Restituisce pioggia cumulata periodo, umidità media,
    range temperature, previsione 7 giorni futuri.
    """
```

### Tool di Azione

```python
@mcp.tool()
async def move_focus_area(field_id: str, x: int, y: int) -> dict:
    """
    Sposta il riquadro di supervisione dell'agente sulla cella (x,y).
    Registra evento di ispezione e aggiorna last_inspected_at.
    Notifica via SSE il client del nuovo focus.
    """

@mcp.tool()
async def create_checkpoint(
    field_id: str, x: int, y: int,
    checkpoint_type: str, note: str
) -> dict:
    """
    Crea un checkpoint nella cella (x,y).
    checkpoint_type: disease_found | high_moisture | treatment_done | inspection
    Notifica via SSE il client.
    """

@mcp.tool()
async def start_treatment(
    field_id: str, x: int, y: int,
    treatment_type: str   # chemical | biological | irrigation | pruning
) -> dict:
    """
    Avvia un trattamento sulla cella.
    Crea record in agent_tasks con ends_at_sim = sim_time +
    treatment_duration_h e imposta status cella a 'under_treatment'.
    Il task verrà chiuso dal field_engine quando l'orologio simulato
    raggiunge ends_at_sim.
    Restituisce ends_at_sim e task_id.
    """

@mcp.tool()
async def advance_simulation_time(field_id: str, hours: int) -> dict:
    """
    Avanza l'orologio simulato del campo di N ore.
    Ricalcola: meteo, moisture, rischio malattia per ogni cella,
    avanza i task in corso, genera eventi se necessario.
    Notifica SSE il client con delta stato.
    """
```

### Tool di Knowledge

```python
@mcp.tool()
async def query_disease_catalog(
    crop_type: str,
    symptoms: list[str] = None,
    weather_conditions: dict = None
) -> list[dict]:
    """
    Restituisce malattie compatibili con i sintomi osservati
    e le condizioni meteo attuali, ordinate per probabilità.
    """

@mcp.tool()
async def get_care_protocol(disease_id: str) -> dict:
    """
    Restituisce il protocollo di cura completo per una malattia:
    azione raccomandata, prodotti, durata, note agronomiche.
    """
```

---

## Motore di Simulazione (field_engine.py)

Il motore è il cuore del sistema. Gira sia in modo sincrono (su `advance_simulation_time`)
sia in background, tramite un task `asyncio` nel processo MCP Server che ogni
`FIELD_TICK_INTERVAL_MINUTES` minuti reali avanza la simulazione di 1 ora.

**Concorrenza:** il tick di background e `advance_simulation_time` mutano lo stesso
stato. Ogni esecuzione di `run_field_tick` acquisisce un advisory lock Postgres
per `field_id` (`pg_advisory_xact_lock`): due tick sullo stesso campo non possono
sovrapporsi, senza bisogno di infrastruttura aggiuntiva.

### Logica tick principale

```python
def run_field_tick(field_id: str, delta_hours: int):
    """
    0. Acquisisce advisory lock transazionale sul field_id
    1. Avanza sim_time e aggiorna meteo: genera/legge dati simulati per le ore
    2. Chiude i task scaduti: per ogni agent_tasks in_progress
       con ends_at_sim <= sim_time:
          - status task = 'completed', completed_at_sim = ends_at_sim
          - cella: active_disease_id = NULL, health_score = 0.7
            (recovery graduale), status = 'treated'
          - genera field_event 'treatment_completed' + SSE task_completed
    3. Per ogni cella:
       a. Aggiorna soil_moisture (pioggia + evaporazione)
       b. Aggiorna soil_temperature (da meteo)
       c. Calcola disease_risk_score:
          - Se cella è sana: P(contagio) basata su:
              * moisture > 0.7 → +0.3
              * humidity > 80% → +0.2
              * temp in range favorevole malattia dominante → +0.3
              * cella adiacente ha malattia attiva → +0.4
          - Se disease_risk_score > 0.85 → attiva malattia
       d. Se cella ha malattia attiva e nessun task cura:
          - health_score -= spread_speed_factor * delta_hours
    4. Genera field_events per anomalie rilevate
    5. Commit, poi emetti SSE update al client (mai prima del commit)
    """
```

### Calcolo bisogno irrigazione

```python
def irrigation_needed(cell) -> bool:
    """
    soil_moisture < 0.3 AND forecast_rain_48h < 5mm → True
    """
```

---

## LangGraph Agent (agent.py)

### Grafo ReAct

```python
# Nodi del grafo
nodes = [
    "observe",          # get_field_state, identifica aree critiche
    "plan",             # decide prossima azione
    "act",              # chiama tool MCP
    "respond",          # genera risposta in linguaggio naturale
]

# Tool disponibili (binding da mcp_client)
tools = [
    get_field_state,
    get_cell_detail,
    move_focus_area,
    capture_field_photo,
    create_checkpoint,
    start_treatment,
    advance_simulation_time,
    get_weather_summary,
    query_disease_catalog,
    get_care_protocol,
]
```

### System Prompt

```
Sei AgroAgent, un agronomo AI specializzato in viticoltura.
Supervisioni un campo di vite simulato tramite sensori, droni e
modelli meteo.

Quando ricevi una richiesta:
1. Prima osserva lo stato corrente del campo (get_field_state)
2. Se ti viene chiesto di ispezionare un'area, sposta il focus
   (move_focus_area) e cattura una foto (capture_field_photo)
3. Interpreta sensori + foto + meteo per valutare rischio
4. Se rilevi problemi, crea sempre un checkpoint
5. Se ti viene chiesto di intervenire, avvia un task di cura
   e spiega la durata attesa
6. Rispondi sempre in italiano, con linguaggio agronomico
   semplice e operativo
7. Segnala proattivamente se ci sono aree ad alto rischio
   che l'utente non ha ancora ispezionato

Non inventare dati dei sensori: usa sempre i tool per leggere
lo stato reale del campo simulato.
```

### Binding del modello

```python
llm = ChatOpenAI(
    base_url=os.environ["OPENAI_BASE_URL"],   # es. https://<tunnel>.trycloudflare.com/v1
    api_key=os.environ["OPENAI_API_KEY"],      # stesso valore passato a vLLM --api-key
    model=os.environ["LLM_MODEL"],             # es. Qwen/Qwen3-32B (o variante quantizzata)
    temperature=0.2,
)
```

---

## LLM — Qwen3 servito da vLLM su Google Colab

L'LLM gira su Colab Pro (GPU A100) con vLLM, che espone nativamente l'API
OpenAI-compatible. Lo stack Docker locale lo raggiunge tramite tunnel HTTPS.

### Notebook Colab (celle essenziali)

```bash
pip install -U vllm

# Server OpenAI-compatible con tool calling abilitato (necessario per l'agente).
# Scegliere la variante Qwen3 più recente che sta nella VRAM della A100
# (40/80 GB a seconda dell'istanza; usare quantizzazione AWQ/FP8 se serve).
vllm serve Qwen/Qwen3-32B \
    --api-key "$VLLM_API_KEY" \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
    --port 8000
```

```bash
# Tunnel HTTPS (nessun account richiesto con cloudflared quick tunnel)
cloudflared tunnel --url http://localhost:8000
# → stampa l'URL pubblico, es. https://xyz.trycloudflare.com
```

### Collegamento allo stack Docker

Nel `.env` locale:

```
OPENAI_BASE_URL=https://xyz.trycloudflare.com/v1
OPENAI_API_KEY=<lo stesso VLLM_API_KEY del notebook>
LLM_MODEL=Qwen/Qwen3-32B
```

### Vincoli da rispettare

- **Tool calling obbligatorio:** l'agente LangGraph usa function calling; vLLM va
  avviato con `--enable-auto-tool-choice` e il parser corretto per Qwen3
  (`hermes`). Senza, i tool MCP non verranno mai invocati.
- **URL effimero:** il tunnel cambia a ogni sessione Colab → `OPENAI_BASE_URL`
  è solo nel `.env`, mai nel codice. Al riavvio di Colab si aggiorna una riga
  e si fa `docker compose up -d agent_service`.
- **Endpoint pubblico = endpoint protetto:** il tunnel è raggiungibile da
  chiunque ne conosca l'URL, quindi `--api-key` su vLLM non è opzionale.
- **Timeout generosi:** prima inferenza lenta (warm-up); impostare timeout
  client ≥ 120s nell'Agent Service.
- **Fallback senza Colab:** qualsiasi endpoint OpenAI-compatible funziona
  (es. Ollama sull'host: `OPENAI_BASE_URL=http://host.docker.internal:11434/v1`).

---

## Web UI — Componenti Principali

### Canvas Campo (field_canvas.js)

```
Dimensioni: 600x600px (10x10 celle, 60px per cella)

Colore cella per stato:
  healthy          → #4CAF50 (verde)
  at_risk          → #FFC107 (giallo)
  diseased         → #F44336 (rosso)
  under_treatment  → #2196F3 (blu, animato)
  treated          → #8BC34A (verde chiaro)

Hover cella:
  → tooltip con: health_score, moisture, temperature, status

Click cella:
  → pannello sensori si apre con dettaglio cella

Overlay checkpoint:
  → icona 📍 sulla cella + colore badge per tipo

Focus box agente:
  → bordo animato (pulse) 2px #FF5722
  → segue move_focus_area via SSE
```

### Pannello Chat

```
- Input testo freeform
- History messaggi con distinzione user/agent
- Indicatore typing quando agente sta lavorando
- Foto simulate mostrate inline nel messaggio
- Link clickable a coordinate cella (click → canvas zoom)
```

### Timeline Eventi

```
- Feed verticale degli ultimi 20 eventi
- Icona per tipo: 🌧️ pioggia | 🦠 malattia | 💊 cura | 📍 checkpoint | ⏭️ avanzamento tempo
- Click evento → evidenzia cella su canvas
```

### Pannello Sensori

```
Appare quando si clicca una cella o l'agente sposta focus.
Mostra:
  - Gauge soil_moisture
  - Temperatura terreno
  - Health score (barra colorata)
  - Malattia attiva (nome + badge severità)
  - Ultima foto (thumbnail)
  - Checkpoint attivi sulla cella
  - Task in corso con timer countdown
```

---

## SSE Events (Server → Client)

Il MCP Server emette questi eventi via `/events/{field_id}` (SSE).
Lo stream invia un commento heartbeat (`: ping`) ogni 15s per tenere viva la
connessione attraverso i proxy; la riconnessione è gestita nativamente da
`EventSource`, e alla riconnessione il client rifà un fetch completo dello stato
via `GET /api/fields/{field_id}` (più semplice e robusto che gestire `Last-Event-ID`).

```json
{ "event": "field_update",
  "data": { "cells": [...], "sim_time": "..." }}

{ "event": "focus_moved",
  "data": { "x": 3, "y": 7 }}

{ "event": "checkpoint_created",
  "data": { "x": 3, "y": 7, "type": "disease_found", "note": "..." }}

{ "event": "task_started",
  "data": { "task_id": "...", "x": 3, "y": 7,
            "ends_at_sim": "..." }}

{ "event": "task_completed",
  "data": { "task_id": "...", "x": 3, "y": 7 }}

{ "event": "time_advanced",
  "data": { "delta_hours": 24, "new_sim_time": "...",
            "events_generated": [...] }}
```

---

## Seed Data — 5 Malattie Vite

```json
[
  {
    "name": "Peronospora della vite",
    "pathogen_type": "oomycete",
    "symptoms_visible": ["macchie oleose foglia", "peluria bianca pagina inferiore"],
    "favorable_temp_min": 11,
    "favorable_temp_max": 30,
    "favorable_humidity_min": 75,
    "spread_speed": "fast",
    "severity_score": 5,
    "treatment_duration_h": 72,
    "recommended_action": "Trattamento con fungicida rameico o sistemico anti-peronospora",
    "image_folder": "peronospora"
  },
  {
    "name": "Oidio della vite",
    "pathogen_type": "fungus",
    "symptoms_visible": ["polverulenza bianca pagina superiore", "deformazione foglie giovani"],
    "favorable_temp_min": 20,
    "favorable_temp_max": 35,
    "favorable_humidity_min": 40,
    "spread_speed": "medium",
    "severity_score": 4,
    "treatment_duration_h": 48,
    "recommended_action": "Trattamento con zolfo bagnabile o IBE",
    "image_folder": "oidio"
  },
  {
    "name": "Botrite (Muffa grigia)",
    "pathogen_type": "fungus",
    "symptoms_visible": ["muffa grigia grappolo", "marcescenza bacche"],
    "favorable_temp_min": 15,
    "favorable_temp_max": 25,
    "favorable_humidity_min": 85,
    "spread_speed": "fast",
    "severity_score": 4,
    "treatment_duration_h": 96,
    "recommended_action": "Diradamento grappoli, trattamento con botricicidi specifici",
    "image_folder": "botrite"
  },
  {
    "name": "Flavescenza Dorata",
    "pathogen_type": "phytoplasma",
    "symptoms_visible": ["ingiallimento foglie", "arrotolamento lembo", "mancata lignificazione tralci"],
    "favorable_temp_min": 20,
    "favorable_temp_max": 32,
    "favorable_humidity_min": 50,
    "spread_speed": "slow",
    "severity_score": 5,
    "treatment_duration_h": 240,
    "recommended_action": "Lotta al vettore Scaphoideus titanus, estirpo piante colpite",
    "image_folder": "flavescenza"
  },
  {
    "name": "Escoriosi",
    "pathogen_type": "fungus",
    "symptoms_visible": ["macchie nere tralci", "disseccamento gemme", "necrosi corteccia"],
    "favorable_temp_min": 5,
    "favorable_temp_max": 20,
    "favorable_humidity_min": 70,
    "spread_speed": "slow",
    "severity_score": 3,
    "treatment_duration_h": 120,
    "recommended_action": "Potatura epuratrice, trattamenti in pre-germogliamento",
    "image_folder": "escoriosi"
  }
]
```

---

## Dataset Immagini — Fonti Consigliate

### PlantVillage Dataset
- **URL:** https://github.com/spmohanty/plantvillage-dataset
- **Specie rilevanti per vite:** Grape___Black_rot, Grape___Esca_(Black_Measles),
  Grape___Leaf_blight_(Isariopsis_Leaf_Spot), Grape___healthy
- **Licenza:** CC BY 4.0
- **Note:** Immagini su sfondo controllato. Usare come fallback per malattie
  che non trovano corrispondenza perfetta con le 5 malattie italiane.

### Multi-Crop Disease Dataset 2025 (Mendeley)
- **URL:** https://data.mendeley.com/datasets/6243z8r6t6
- **Contenuto:** 23.000+ immagini da campo reale, variabilità illuminazione
- **Licenza:** CC BY 4.0
- **Note:** Più realistico di PlantVillage per la simulazione "foto da drone"

### Struttura cartelle locali
```
data/images/
├── healthy/
│   └── vite_sana_001.jpg ... vite_sana_050.jpg
└── diseased/
    ├── peronospora/   → 20-30 immagini
    ├── oidio/         → 20-30 immagini
    ├── botrite/       → 20-30 immagini
    ├── flavescenza/   → 20-30 immagini
    └── escoriosi/     → 20-30 immagini
```

La funzione `capture_field_photo` sceglie random un'immagine dalla cartella
corrispondente allo stato della cella e la restituisce come path.

---

## API Endpoints

### MCP Server (:8001)

```
/mcp                                — Endpoint MCP Streamable HTTP (FastMCP),
                                      richiede Authorization: Bearer <MCP_AUTH_TOKEN>
GET  /events/{field_id}             — SSE stream aggiornamenti campo
GET  /api/fields/{field_id}         — Stato completo campo (HTTP fallback)
GET  /api/fields/{field_id}/cells   — Griglia celle
POST /api/fields                    — Crea nuovo campo
GET  /images/...                    — Serve immagini dataset via StaticFiles di
                                      Starlette montato su data/images (gestisce
                                      già la protezione path traversal; non
                                      implementare a mano un open() su path
                                      ricevuti dal client)
```

CORS: allowlist esplicita sull'origin del frontend (`http://localhost:3000`),
mai `*`. Gli endpoint `/api` e `/events` sono consumati dal browser; `/mcp` no
(solo Agent Service, server-to-server sulla rete interna).

### Agent Service (:8002)

```
POST /chat                          — Messaggio chat, restituisce risposta agente
GET  /chat/{session_id}/history     — Storico conversazione
```

### Frontend (:3000)

```
GET /                               — index.html (single page app)
```

---

## Docker Compose

Scelte di sicurezza e robustezza applicate al compose:
- niente chiave `version:` (deprecata in Compose v2)
- nessuna credenziale hardcoded: tutto da `.env` (che è in `.gitignore`)
- Postgres **senza** porta pubblicata sull'host: raggiungibile solo dalla
  rete interna Compose (per ispezionare il DB in dev: `docker compose exec postgres psql`)
- healthcheck su Postgres + `depends_on: condition: service_healthy`,
  così le migration non partono prima che il DB accetti connessioni
- volume immagini montato read-only dove serve solo lettura
- porte applicative bindate su `127.0.0.1` (demo locale, non esposta in LAN)

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10

  mcp_server:
    build: ./mcp_server
    ports:
      - "127.0.0.1:8001:8001"
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres/${POSTGRES_DB}
      MCP_AUTH_TOKEN: ${MCP_AUTH_TOKEN}
      FRONTEND_ORIGIN: http://localhost:3000
      FIELD_TICK_INTERVAL_MINUTES: ${FIELD_TICK_INTERVAL_MINUTES}
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./data:/app/data:ro

  agent_service:
    build: ./agent_service
    ports:
      - "127.0.0.1:8002:8002"
    environment:
      OPENAI_BASE_URL: ${OPENAI_BASE_URL}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      LLM_MODEL: ${LLM_MODEL}
      MCP_SERVER_URL: http://mcp_server:8001/mcp
      MCP_AUTH_TOKEN: ${MCP_AUTH_TOKEN}
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres/${POSTGRES_DB}
      FRONTEND_ORIGIN: http://localhost:3000
    depends_on:
      postgres:
        condition: service_healthy
      mcp_server:
        condition: service_started

  frontend:
    image: nginx:alpine
    ports:
      - "127.0.0.1:3000:80"
    volumes:
      - ./frontend:/usr/share/nginx/html:ro

volumes:
  pgdata:
```

---

## Variabili di Ambiente (.env.example)

Il file `.env` reale non si committa mai (`.gitignore`); `.env.example` contiene
solo placeholder, nessun valore di default per le credenziali.

```
OPENAI_BASE_URL=                 # endpoint vLLM su Colab via tunnel, es. https://xyz.trycloudflare.com/v1
OPENAI_API_KEY=                  # api-key impostata su vLLM (--api-key), mai loggata né esposta al frontend
LLM_MODEL=Qwen/Qwen3-32B
POSTGRES_DB=agroagent
POSTGRES_USER=agroagent
POSTGRES_PASSWORD=               # generare: openssl rand -hex 16
MCP_AUTH_TOKEN=                  # bearer token agent_service → mcp_server: openssl rand -hex 32
MCP_SERVER_URL=http://mcp_server:8001/mcp
AGENT_SERVICE_URL=http://agent_service:8002
FIELD_TICK_INTERVAL_MINUTES=5
DEFAULT_FIELD_ROWS=10
DEFAULT_FIELD_COLS=10
IMAGE_BASE_PATH=/app/data/images
```

---

## Sicurezza — Baseline MVP

Contesto: demo locale single-user, ma senza scorciatoie che diventino debiti.

1. **Segreti.** Credenziali e token solo via variabili d'ambiente da `.env`
   (gitignored). La `OPENAI_API_KEY` dell'endpoint LLM vive solo nell'Agent
   Service: non passa mai per il frontend né compare nei log. L'endpoint vLLM
   esposto via tunnel è sempre protetto da api-key (vedi sezione LLM).
2. **Autenticazione MCP.** L'endpoint `/mcp` richiede `Authorization: Bearer
   <MCP_AUTH_TOKEN>` (token statico condiviso via env, confronto constant-time).
   La spec MCP prevede OAuth 2.1 per server remoti pubblici: fuori scope per
   l'MVP, da adottare se il server venisse mai esposto su Internet.
3. **Superficie di rete.** Postgres senza porta sull'host; porte applicative
   bindate su 127.0.0.1; CORS con allowlist esplicita dell'origin frontend.
4. **Validazione input.** Tutti i parametri dei tool MCP e degli endpoint HTTP
   validati server-side con Pydantic (bounds griglia, range ore, enum `Literal`).
   Query SQL solo tramite SQLAlchemy (parametrizzate), mai string interpolation.
5. **Agente LLM.** Loop ReAct con tetto massimo di iterazioni (es. 15) e tool
   allowlist fissa: l'agente può agire solo tramite i 10 tool MCP definiti.
   I risultati dei tool sono dati, non istruzioni: il system prompt non viene
   mai concatenato con contenuto proveniente dal campo senza delimitazione.
6. **File serving.** Immagini servite via `StaticFiles` su directory dedicata
   montata read-only nel container; nessun path costruito da input utente.
7. **Dipendenze.** Versioni pinnate (`requirements.txt` con lock o `uv lock`);
   immagini Docker con tag espliciti, non `latest`.

---

## Roadmap a Sprint

### Sprint 1 — Fondazione (3-4 giorni)
- [ ] Setup Docker Compose con postgres + .env + .gitignore
- [ ] Schema DB + Alembic migrations
- [ ] Seed data malattie (5 vite) + import immagini PlantVillage (subset uva)
- [ ] Creazione campo iniziale via API
- [ ] MCP Server (FastMCP, streamable HTTP, bearer auth) con tool `get_field_state` e `get_cell_detail`

### Sprint 2 — Motore simulazione (3-4 giorni)
- [ ] field_engine.py: tick meteo, aggiornamento moisture, calcolo disease_risk
- [ ] Logica contagio tra celle adiacenti
- [ ] Chiusura task a tempo simulato (ends_at_sim) + tick asyncio di background con advisory lock
- [ ] MCP tool: `advance_simulation_time`, `start_treatment`, `capture_field_photo`
- [ ] SSE endpoint funzionante (heartbeat + refetch su riconnessione)

### Sprint 3 — Agent LangGraph (2-3 giorni)
- [ ] MCP client wrapper
- [ ] LangGraph ReAct graph con tool binding
- [ ] System prompt agronomo viticoltore
- [ ] `/chat` endpoint Agent Service
- [ ] Test conversazione base: osserva, ispeziona, diagnosi, trattamento

### Sprint 4 — UI Canvas (3-4 giorni)
- [ ] Grid canvas 10×10 con colori per stato
- [ ] SSE client → aggiornamento canvas real-time
- [ ] Focus box animato
- [ ] Pannello sensori on-click
- [ ] Layer checkpoint (icone sulla mappa)
- [ ] Pannello chat integrato

### Sprint 5 — Polish demo (2 giorni)
- [ ] Timeline eventi
- [ ] Foto simulate inline in chat
- [ ] Task countdown nel pannello sensori
- [ ] Demo flow completo: osserva → diagnosi → checkpoint → cura → avanza tempo → risoluzione
- [ ] README con setup e GIF demo

---

## Prompt per Claude Code

Quando passi questo documento a Claude Code, usa questo prompt:

```
Leggi il piano tecnico allegato (agroagent_piano_tecnico.md) per intero.

Inizia dallo Sprint 1:
1. Crea la struttura di cartelle del progetto nella root del repo (Hay_simulator/)
2. Scrivi il docker-compose.yml esattamente come specificato
3. Crea .env.example e .gitignore (che esclude .env)
4. Scrivi tutti i SQLAlchemy models (mcp_server/models/)
5. Scrivi le Alembic migrations
6. Scrivi il seed data JSON per le 5 malattie della vite
7. Scrivi uno script di seed che importa i dati nel DB al primo avvio
8. MCP Server FastMCP (streamable HTTP) con bearer auth e i primi due tool

Non procedere agli sprint successivi finché Sprint 1 non è completo e testato.
Per ogni file creato, mostrami il contenuto completo senza truncation.
```

Poi per Sprint 2:

```
Sprint 1 completato. Procedi con Sprint 2.
Implementa field_engine.py con:
- run_field_tick(field_id, delta_hours) con advisory lock per field_id
- calcolo moisture basato su pioggia ed evaporazione
- calcolo disease_risk_score per cella con regole dal seed data
- logica contagio tra celle adiacenti (raggio 1)
- chiusura dei task scaduti in base a ends_at_sim (tempo simulato)
Poi implementa il tick asyncio di background nel MCP Server.
Poi implementa i MCP tool: advance_simulation_time, start_treatment, capture_field_photo.
Mostrami ogni file completo.
```

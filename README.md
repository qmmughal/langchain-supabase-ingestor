# LangChain + Supabase: Real-Time Data Ingestion & Alerting

A **production-grade** system that ingests data from external REST APIs, processes it with LangChain + local LLMs (Ollama), and fires intelligent in-app alerts — all powered by Supabase Realtime.

---

## Architecture

```
REST APIs (GitHub, FDA, Weather…)
        │  poll
        ▼
  Ingestor Service (Python + LangChain)
  ├── Fetch & deduplicate raw events
  ├── Chunk + embed (Ollama / nomic-embed-text)
  ├── Summarise & tag (Ollama / llama3)
  └── Upsert to Supabase
        │
        ▼
  Supabase (PostgreSQL + pgvector + Realtime)
        │  INSERT triggers Realtime broadcast
        ▼
  Alert Engine (Python + LangChain)
  ├── Load active alert rules
  ├── Evaluate: keyword | semantic | LLM agent
  └── Write alert to alert_log → Realtime push
        │
        ▼
  Next.js Dashboard
  ├── Live event feed (WebSocket)
  ├── Unread alert badge + notifications
  ├── Alert rules CRUD
  └── Semantic search (pgvector)
```

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | ≥ 3.11 | [python.org](https://python.org) |
| Node.js | ≥ 18 | [nodejs.org](https://nodejs.org) |
| Ollama | latest | [ollama.com](https://ollama.com) |
| Docker (optional) | latest | [docker.com](https://docker.com) |

---

## Quick Start

### 1. Clone & configure

```bash
git clone <repo-url>
cd langchain-supabase-ingestor

# Copy env template
cp .env.example .env
# Edit .env with your Supabase URL + keys
```

### 2. Set up Supabase

1. Create a free project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** and run the migrations in order:
   ```
   supabase/migrations/001_schema.sql
   supabase/migrations/002_realtime.sql
   supabase/migrations/003_rls.sql
   ```
3. Copy your **Project URL**, **anon key**, and **service role key** into `.env`
4. Enable **Realtime** in your Supabase dashboard under Database → Replication

### 3. Pull Ollama models

```bash
ollama pull nomic-embed-text   # embeddings (768-dim)
ollama pull llama3             # LLM for agent evaluation
```

### 4. Install Python backend

```bash
cd backend
pip install -r requirements.txt
```

### 5. Run the backend services

**Option A — separate terminals:**
```bash
# Terminal 1: FastAPI
uvicorn backend.api.main:app --reload --port 8000

# Terminal 2: Ingestor (poll every 60s)
python -m backend.ingestor.main --loop --interval 60

# Terminal 3: Alert engine (Realtime subscriber)
python -m backend.alert_engine.engine
```

**Option B — Docker Compose (all services):**
```bash
docker-compose up --build
```

### 6. Run the frontend

```bash
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anon/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key (backend only) |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`) |
| `OLLAMA_EMBED_MODEL` | Embedding model (default: `nomic-embed-text`) |
| `OLLAMA_LLM_MODEL` | LLM model (default: `llama3`) |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase URL for the browser |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key for the browser |
| `NEXT_PUBLIC_API_URL` | FastAPI base URL (default: `http://localhost:8000`) |

---

## Data Sources

Three sources are seeded by default:
- **GitHub Public Events** — polls `api.github.com/events` every 60s
- **Open-Meteo Weather (Berlin)** — current weather every 5 min
- **FDA Drug Recalls** — OpenFDA enforcement data every 10 min

Add more via the dashboard or directly in the `data_sources` table.

---

## Alert Rules

Rules support three evaluation modes:

| Mode | How it works | LLM cost |
|---|---|---|
| **Keyword** | Regex word-boundary match on title/content/tags | None |
| **Semantic** | Cosine similarity between doc embedding and reference text | Embedding only |
| **LLM Agent** | LLM reads the event and decides YES/NO | Full inference |

Rules fire at most once per `cooldown_seconds` (default 5 min).

---

## API Reference

The FastAPI server exposes a full REST API documented at `http://localhost:8000/docs`.

Key endpoints:
- `GET /stats` — dashboard summary
- `GET /documents` — paginated processed documents
- `POST /documents/search` — semantic vector search
- `GET/POST /rules` — alert rule management
- `GET /alerts` — alert log
- `PATCH /alerts/{id}/read` — mark alert as read

---

## Running Tests

```bash
cd backend
pytest tests/ -v
```

---

## Project Structure

```
├── backend/
│   ├── shared/
│   │   ├── models.py          # Pydantic data models
│   │   ├── supabase_client.py # Supabase client
│   │   └── ollama_client.py   # Ollama LLM + embeddings
│   ├── ingestor/
│   │   ├── loaders.py         # REST API fetchers
│   │   ├── pipeline.py        # LangChain ingestion chain
│   │   └── main.py            # Scheduler entry point
│   ├── alert_engine/
│   │   ├── evaluator.py       # Keyword/semantic/LLM evaluator
│   │   └── engine.py          # Realtime subscriber
│   ├── api/
│   │   └── main.py            # FastAPI REST API
│   └── tests/
├── frontend/                  # Next.js dashboard
├── supabase/
│   └── migrations/
│       ├── 001_schema.sql     # Tables + pgvector
│       ├── 002_realtime.sql   # Realtime publication
│       └── 003_rls.sql        # Row-level security + seed data
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Deployment

### Backend → Railway / Fly.io
Each Python service is independently deployable.

### Frontend → Vercel
```bash
cd frontend && vercel deploy
```

### Database → Supabase Cloud (already hosted)
Supabase handles PostgreSQL, pgvector, Realtime, and auth out of the box.

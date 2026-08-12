# Logos Mind - Backend API

FastAPI backend for Logos Mind. Bilingual Bible + sermon search over Supabase `pgvector` (`text-embedding-3-small` via OpenRouter), streaming agentic chat, and a bilingual CLI. Book-name handling is centralized in `books.py` (single source of truth for `KO_TO_EN`).

## Features

- **Bilingual Bible Search:** `NKRV` for Korean queries, `ESV` for English — auto-detected via `books.py:detect_version()` (Hangul regex), or explicit `?version=`
- **Exact Text / Multi-Chapter Retrieval:** `GET /api/bible/text` and `GET /api/bible/chapters` accept Korean or English book names (any case) via `books.py:to_db_book()` / `db_book_names()`. Single version → flat array, `?version=all` / `NKRV,ESV` → `{ "NKRV": [...], "ESV": [...] }` (ESV capped at 500 verses)
- **Sermon Quote Retrieval:** `GET /api/sermons/search` over `sermons` chunks
- **Streaming Agentic Chat:** `POST /api/chat/stream` (SSE) — tool-calling loop (`search_bible`, `get_bible_text`, `find_pastor_quotes`) with citations and `thought`, sanitized `history`, ESV copyright appended for English answers
- **Bilingual CLI:** `bin/bible` / `cli/` — one-shot `text`/`search`/`sermons`/`chat` + interactive REPL
- **Auto-generated Docs:** Swagger UI / ReDoc / OpenAPI

## Prerequisites

- Python 3.13+ (see `pyproject.toml: requires-python >=3.13`)
- [`uv`](https://github.com/astral-sh/uv)
- Supabase with `pgvector` and tables `bible_verses`, `bible_sections` (+ `match_bible_sections_v` RPC), `sermons` (+ `match_sermons` RPC)
- **OpenRouter API key** (embeddings `openai/text-embedding-3-small` and chat `AGENT_MODEL` both go through `https://openrouter.ai/api/v1`)
- **ESV API key** (only for `scripts/ingest_esv.py` / `extract_pericopes.py`)
- SSH access to the VPS (only for `scripts/schema_update.py`, `remote_sql_exec.py`)

## Setup

1. **Environment Variables** — create `.env` in the repo root:

   ```env
   SUPABASE_URL=http://76.13.110.111:8000
   SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
   OPENROUTER_API_KEY=sk-or-v1-...
   ESV_API_KEY=your_esv_api_key
   # optional — defaults to moonshotai/kimi-k2.6 if unset
   AGENT_MODEL=deepseek/deepseek-chat
   ```

   For VPS-direct SQL (`scripts/schema_update.py`, `scripts/remote_sql_exec.py`):

   ```env
   SSH_HOST=76.13.110.111
   SSH_USER=root
   SSH_PASSWORD=your-ssh-password
   ```

2. **Install Dependencies**

   ```bash
   uv sync
   # frozen in CI: uv sync --frozen
   ```

## Running the Server

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

- Local: `http://localhost:8080`
- Live (self-hosted on Hostinger KVM): `http://76.13.110.111:8080`
- Health: `GET /health` → `{"status":"healthy"}`

## API Documentation

- **Swagger UI:** `http://localhost:8080/docs` (live: `http://76.13.110.111:8080/docs`)
- **ReDoc:** `http://localhost:8080/redoc` (live: `http://76.13.110.111:8080/redoc`)
- **OpenAPI JSON:** `http://localhost:8080/openapi.json` (live: `http://76.13.110.111:8080/openapi.json`)

## Core Endpoints

- `GET /health` — liveness check

- `GET /api/bible/search`
  - `query` (string, required), `limit` (int 1–20, default 5), `version` (`NKRV` or `ESV`; auto-detected from `query` language, `all`/`NKRV,ESV` returns `422` — search is per-version)
  - Calls `match_bible_sections_v` RPC (`match_threshold 0.3`), stamps `version`/`copyright` (ESV)

- `GET /api/bible/text`
  - `book` (Korean or English, any case), `chapter` (int), `verse_start` (int), `verse_end` (int, optional, inclusive), `version` (`NKRV`, `ESV`, `all`, or `NKRV,ESV`/`ESV,NKRV`; default by `detect_version(book)`)
  - Returns `VerseResponse[]` for one version, or `{ "NKRV": [...], "ESV": [...] }` for `all`; capped at 500 rows per response

- `GET /api/bible/chapters`
  - `book`, `chapter_start` (int), `chapter_end` (int, optional), `version` (same as `/text`)
  - Same grouping/cap as `/text`, ordered by `chapter`, `verse_start`, `version`

- `GET /api/sermons/search`
  - `query` (string), `limit` (int 1–10, default 3)
  - Calls `match_sermons` RPC (`match_threshold 0.4`)

- `POST /api/chat/stream`
  - Body: `{ "message": string, "history": [{role, content}] | null }` — `history` is sanitized (last 10, drops non-dict/`null`/empty `content` entries)
  - SSE: `data: {"type":"delta","content": string}` … `data: {"type":"done","answer": string,"thought": string,"citations": [{book, chapter, verse_start, verse_end}]}` or `data: {"type":"error","detail": string}`
  - System prompt and citations are version-aware (`NKRV` ↔ `ESV`; ESV answers end with `ESV_COPYRIGHT`)

> `POST /api/chat` (non-streaming) was removed; use `POST /api/chat/stream` for all chat.

## CLI

The repo ships an opencode-style CLI (`bin/bible` → `cli/main.py`) against the same API. It defaults to the live VPS (`http://76.13.110.111:8080`) and streams chat via `POST /api/chat/stream`.

```bash
# one-time
uv sync

# help
uv run python -m cli.main --help
# or via wrapper
./bin/bible --help
bin/bible text --help
```

**One-shot commands:**

```bash
# exact verse lookup (Korean or English, any case)
./bin/bible text "시편 23:1-3"
./bin/bible text "Genesis 1:1" --version ESV
./bin/bible text "Genesis 1:1" --version all   # {"NKRV": [...], "ESV": [...]}

# semantic search (bible_sections)
./bin/bible search "천지창조" --limit 5
./bin/bible search "the good shepherd" --limit 5 --version ESV

# sermon archive search
./bin/bible sermons "십자가" --limit 3

# agentic chat (streaming, same as REPL)
./bin/bible chat "Explain Genesis 1 creation"
./bin/bible chat "천지창조에 대해 설명해줘" --no-copyright
```

**REPL (interactive):**

```bash
./bin/bible repl   # or just: ./bin/bible
```

Inside `bible> `:

```
시편 23:1              # bare verse ref → exact lookup
/search 천지창조      # semantic search
/sermons 십자가        # sermon search
/reset               # clear conversation history
/copyright           # toggle ESV copyright footer
/help                # show commands
/quit                # exit (also /exit, /q, Ctrl-D)
```

Any other line is treated as a chat question and streams `POST /api/chat/stream` with conversation history (`convo` in `cli/main.py:_repl`).

**Pointing at a different API:**

```bash
BIBLE_API_URL=http://localhost:8080 ./bin/bible search "hello"
./bin/bible --api-url http://localhost:8080 chat "hello"
```

## Testing

Tests are ad-hoc scripts in `tests/` (not `pytest`) that hit the API over HTTP. Start the server first:

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8080 --reload
# health check
curl http://localhost:8080/health
```

Then:

```bash
uv run python tests/test_chat.py        # streaming chat (POST /api/chat/stream SSE)
uv run python tests/test_api_search.py  # GET /api/bible/search
uv run python tests/test_reasoning.py   # GET /api/bible/search (reasoning query)
uv run python tests/test_esv_pericopes.py  # hits live ESV API (needs ESV_API_KEY in .env)
uv run python tests/test_single.py      # ESV HTML fetch (needs ESV_API_KEY)
```

All `tests/*.py` default to `BASE_URL = "http://localhost:8080"`. To run against the deployed VPS, either edit `BASE_URL` or run a one-liner:

```bash
BASE_URL=http://76.13.110.111:8080 uv run python tests/test_chat.py
# or the comprehensive check used in CI/debugging:
uv run python /tmp/run_remote_tests.py   # health, search, text, chapters, chat_stream, CLI
```

## ESV Data Ingestion

The ESV API free tier allows roughly 75 requests/day, so the full Bible (1,189 chapters) is ingested incrementally by the resumable script `scripts/ingest_esv.py` (it skips already-ingested chapters and prioritizes commonly used books). It now imports book names from `books.py` (`KO_TO_EN`, `ko_to_en`). A GitHub Actions workflow (`.github/workflows/ingest-esv.yml`) runs it daily at 05:30 UTC on the self-hosted runner; it can also be triggered manually via `workflow_dispatch`.

The script reads `ESV_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `OPENROUTER_API_KEY` from the environment. To run manually: `uv run python scripts/ingest_esv.py`.

`pericope_map.json` (pericope/chunk boundaries) is built by `scripts/extract_pericopes.py` (also via `books.py`).

Schema migrations (e.g., the `version` column and the `match_bible_sections_v` RPC) live in `scripts/schema_update.py`, which runs SQL on the VPS over SSH using the `SSH_*` environment variables.

## Deployment

- `Dockerfile` (`python:3.12-slim` + `uv pip install --system -r pyproject.toml`) is built on the self-hosted Hostinger KVM runner (`76.13.110.111`).
- GitHub Actions `.github/workflows/deploy.yml` triggers on `push` to `main`: `docker build -t bible-backend`, `docker stop/rm`, `docker run -d -p 8080:8080 --network=supabase_default --env-file /root/app/.env --restart always bible-backend:latest`.
- Live Swagger: `http://76.13.110.111:8080/docs` (`/openapi.json`, `/redoc`, `/health` alongside).
- Local `docker-compose` on the VPS provides Supabase (`supabase-kong:8000`, `supabase_default` network) — the `ingest-esv.yml` workflow exports `SUPABASE_URL=http://76.13.110.111:8000` for the host-side ingestion.

## Project Layout

```
books.py            # single source of truth for KO_TO_EN + helpers (detect_version, to_db_book, ...)
agent.py            # BibleAgent (tool loop, citations, streaming)
main.py             # FastAPI app + /api/* routes
cli/                # bilingual CLI (client.py, parser.py, render.py, main.py)
bin/bible           # wrapper → uv run -m cli.main
tests/              # ad-hoc API scripts (chat, search, ESV)
scripts/            # ingest_esv, extract_pericopes, apply_chunking, schema_update
pericope_map.json   # chunk boundaries for bible_sections
```

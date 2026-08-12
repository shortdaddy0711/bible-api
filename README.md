# Logos Mind - Backend API

This directory contains the FastAPI backend for the Logos Mind project. It provides semantic search capabilities over the Bible and Sermon database using OpenAI's embeddings (`text-embedding-3-small`) and Supabase's `pgvector`.

## Features

- **Bilingual Bible Search:** Semantic search returns the Revised Korean Version (개역개정) for Korean queries and the English Standard Version for English queries.
- **Exact Text Retrieval:** Fetch specific books, chapters, and verse ranges in either version.
- **Multi-Chapter Retrieval:** Fetch full text for a range of chapters at once.
- **Sermon Quote Retrieval:** Find relevant sermon excerpts based on a topic or verse reference (Preparation for Phase 3).
- **Auto-generated Documentation:** Interactive API documentation via Swagger UI.

## Prerequisites

- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv) (Fast Python package installer and resolver)
- A running Supabase instance with `pgvector` enabled and the tables created.
- OpenAI API Key.

## Setup

1. **Environment Variables**
   Create a `.env` file in this `backend` directory (you can copy it from the `crawler` directory if you already set it up there):

   ```env
   SUPABASE_URL=http://<your-vps-ip>:8000
   SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
   OPENROUTER_API_KEY=sk-or-your_openrouter_key
   ```

   The maintenance scripts in `scripts/` that run SQL directly on the VPS (`schema_update.py`, `remote_sql_exec.py`) additionally need SSH credentials (never commit these to the repo):

   ```env
   SSH_HOST=your-vps-ip
   SSH_USER=root
   SSH_PASSWORD=your-ssh-password
   ```

2. **Install Dependencies**
   This project uses `uv` for dependency management.

   ```bash
   uv sync
   ```

   _(Alternatively, if you are just adding packages, use `uv add <package>`)_

## Running the Server

To start the FastAPI server locally for development:

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

The server will be available at `http://localhost:8080`.

## API Documentation

Once the server is running, you can access the automatically generated interactive documentation:

- **Swagger UI:** [http://localhost:8080/docs](http://localhost:8080/docs)
- **ReDoc:** [http://localhost:8080/redoc](http://localhost:8080/redoc)

## Core Endpoints

- `GET /api/bible/search`
  - Parameters: `query` (string), `limit` (int), `version` (optional: `NKRV` or `ESV`, auto-detected from query language by default)
  - Description: Performs a vector similarity search on the `bible_sections` table.
- `GET /api/bible/text`
  - Parameters: `book` (string), `chapter` (int), `verse_start` (int), `verse_end` (optional int), `version` (optional)
  - Description: Returns the exact text for the requested passage.
- `GET /api/bible/chapters`
  - Parameters: `book` (string), `chapter_start` (int), `chapter_end` (optional int), `version` (optional)
  - Description: Returns all verses for the requested range of chapters.
- `GET /api/sermons/search`
  - Parameters: `query` (string), `limit` (int)
  - Description: Performs a vector similarity search on the `sermons` table.
- `POST /api/chat/stream`
  - Body: `{ "message": string, "history": Array }`
  - Description: Streaming agentic chat (Server-Sent Events) that uses the Bible and sermon tools to provide theological answers. Yields `data: {"type":"delta","content":...}` chunks then `data: {"type":"done","answer","thought","citations"}`. Answers in the query language (NKRV for Korean, ESV for English).

## CLI

The repo ships an opencode-style CLI (`bin/bible` → `cli/main.py`) against the same API the server exposes. It defaults to the live VPS (`http://76.13.110.111:8080`) and streams chat via `POST /api/chat/stream`.

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

The ESV API free tier allows roughly 75 requests/day, so the full Bible (1,189 chapters) is ingested incrementally by the resumable script `scripts/ingest_esv.py` (it skips already-ingested chapters and prioritizes commonly used books). A GitHub Actions workflow (`.github/workflows/ingest-esv.yml`) runs it daily at 05:30 UTC on the self-hosted runner; it can also be triggered manually via `workflow_dispatch`.

The script reads `ESV_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `OPENROUTER_API_KEY` from the environment. To run manually: `uv run python scripts/ingest_esv.py`.

Schema migrations (e.g., the `version` column and the `match_bible_sections_v` RPC) live in `scripts/schema_update.py`, which runs SQL on the VPS over SSH using the `SSH_*` environment variables.

## Deployment

A `Dockerfile` is included in this directory. It uses `uv` to install dependencies into a lightweight Python 3.12 image. It is designed to be deployed as part of the overall `docker-compose` stack on the VPS.

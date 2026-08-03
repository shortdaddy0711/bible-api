# Logos Mind - Backend API

This directory contains the FastAPI backend for the Logos Mind project. It provides semantic search capabilities over the Bible and Sermon database using OpenAI's embeddings (`text-embedding-3-small`) and Supabase's `pgvector`.

## Features

- **Semantic Bible Search:** Find verses based on meaning, not just exact keywords.
- **Exact Text Retrieval:** Fetch specific books, chapters, and verse ranges.
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
  - Parameters: `query` (string), `limit` (int)
  - Description: Performs a vector similarity search on the `bible_verses` table.
- `GET /api/bible/text`
  - Parameters: `book` (string), `chapter` (int), `verse_start` (int), `verse_end` (optional int)
  - Description: Returns the exact text for the requested passage.
- `GET /api/bible/chapters`
  - Parameters: `book` (string), `chapter_start` (int), `chapter_end` (optional int)
  - Description: Returns all verses for the requested range of chapters.
- `GET /api/sermons/search`
  - Parameters: `query` (string), `limit` (int)
  - Description: Performs a vector similarity search on the `sermons` table.
- `POST /api/chat`
  - Body: `{ "message": string, "history": Array }`
  - Description: Agentic chat interface that uses the Bible and sermon tools to provide theological answers.

## Deployment

A `Dockerfile` is included in this directory. It uses `uv` to install dependencies into a lightweight Python 3.12 image. It is designed to be deployed as part of the overall `docker-compose` stack on the VPS.

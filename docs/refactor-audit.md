# Refactor Audit

- Audited: 2026-10-29, read-only, at `b8d16b3`
- Status re-checked: 2026-11-02, HEAD `e126fb6` + steps 1–2 working tree changes
- Scope: `main.py`, `agent.py`, `books.py`, `cli/`, `scripts/`, `tests/`, `Dockerfile`, `.github/workflows/`, `pyproject.toml`
- Method: code reading plus live measurement where noted. No production writes.

An entry is `OPEN` when the code at HEAD still has the defect, `FIXED` when the commit or working-tree change named changed it. Line references are HEAD `e126fb6` unless a commit is named.

## Summary

| Area | Findings | Open | Fixed |
|---|---|---|---|
| Correctness | 9 | 4 | 5 |
| Architecture | 7 | 6 | 1 |
| Operations | 6 | 6 | 0 |
| Tests and logs | 4 | 4 | 0 |
| **Total** | **26** | **20** | **6** |

## Correctness

| # | Finding | Evidence | Smallest fix | Status |
|---|---|---|---|---|
| 1 | Concurrent chat requests overwrite each other's language. A Korean request can run its tool call with `version_filter=ESV`. Measured with two concurrent streams: the RPC saw `['ESV','ESV','ESV','ESV']`. | `agent.py:105` shared `current_version`; written at `:223`; read at `:144`, `:158`, `:163`; one `BibleAgent` instance at `main.py:39` | Pass the version as a parameter through `run_stream` and the tools, then delete the attribute | FIXED in working tree (step 1): version is per-request; `current_version` deleted; regression test fails on the old code |
| 2 | Multi-version responses drop rows. A 200 returns empty lists when a stored `version` is lowercase or NULL. | `main.py:103-110` filters with `r.get("version") == v`; rows with `version: "nkrv"` and NULL appear in the single-version path and vanish in the multi-version path | Normalize before grouping, or query once per version and assert counts | FIXED in working tree (step 2): one query per version with `ilike("version", v)`; route test covers a stored `"nkrv"` row |
| 3 | `ingest_esv.py` titled every section with the *next* pericope's heading and emitted overlapping ranges. | `scripts/ingest_esv.py` before the fix; the corrected path is `build_sections` (`scripts/ingest_esv.py:153-180`) | Reuse one chunker (see #14) | FIXED in `e126fb6` (code only; production ESV rows still need the one-time rebuild) |
| 4 | The CLI REPL never sends conversation history. Every chat request carries `history: []`. | `cli/main.py:151` creates `convo`; `:165` clears it; nothing appends; `:135` passes it unchanged to `_stream_chat` (`:74`) | Append the user turn and the final answer | OPEN |
| 5 | A client can inject `role: "system"` into `history` and override the system prompt. `ChatRequest.message` has no length bound. | `agent.py:232` accepts `system` and `tool`; `agent.py:10-12` has no length limit | Accept only `user` and `assistant`; cap message length | OPEN |
| 6 | `?version=bogus` returns 404 "Verses not found" instead of 422. | `main.py:100` uppercases any string; `resolve_versions("Genesis","bogus") == ["BOGUS"]` | Validate the parameter as an enum at the route | FIXED in working tree (step 2): `Version` / `SearchVersion` enums; `bogus` is 422 before the handler |
| 7 | Responses silently truncate at 500 rows, after fetching everything and before grouping. | `main.py:171-186`, `:213-228`; no `.limit()` on either query | Limit per version in SQL; return a `truncated` flag and cursor | FIXED in working tree (step 2): `.limit(501)` per version, 500 returned, `truncated` + `next_verse_id`; route test covers 600 rows |
| 8 | `ingest_esv_sections.py` writes sections without `content`, which `SectionResponse` requires. Those rows reach the search RPC. | `scripts/ingest_esv_sections.py:94-103` vs `main.py:89` | Delete the script or write `content` | OPEN |
| 9 | `check_db_status.py` probes an RPC that no file defines. | `scripts/check_db_status.py:60` calls `match_bible_verses`; `scripts/schema_update.py:25` defines only `match_bible_sections_v` | Point it at the real RPC | OPEN |

## Architecture

| # | Finding | Evidence | Smallest fix | Status |
|---|---|---|---|---|
| 10 | Retrieval and licensing live in two places and already disagree: different book and version strategies, copyright stamping only in routes, two embedding ids. | Route query `main.py:171-180`; tool query `agent.py:158-169`; copyright `main.py:186-189`; embedding id `text-embedding-3-small` at `main.py:124` vs `openai/text-embedding-3-small` at `agent.py:130`, `:180`; thresholds `main.py:136,259` vs `agent.py:142,191` | One `retrieval.py` owning queries, thresholds, the 500 cap, and copyright | OPEN |
| 11 | Blocking I/O runs inside `async def` routes, and the SSE route iterates a sync generator. One chat stalls health checks and other requests for the whole stream. | `main.py:113-154` uses sync Supabase/OpenAI clients; `main.py:276` loops `run_stream` inside the async generator | Make unary routes `def` (threadpool); run the stream through `iterate_in_threadpool`, or move to async clients | OPEN |
| 12 | The response contract is a union of two shapes. Generated clients must sniff at runtime; the CLI already loses one version. | `main.py:73`; `cli/client.py:46` takes `list(data.values())[0]` | One envelope with `versions`, `truncated`, and the resolved versions | FIXED in working tree (step 2): `VersesResponse` always; CLI flattens every version; qt-everyday reads `versions` |
| 13 | Config is read and validated at import, so importing the app for tests or scripts requires fake credentials. | `main.py:28-31` raises on missing env; `AGENT_MODEL` read per instance at `agent.py:104` | Settings object validated once at startup; clients built in a lifespan | OPEN |
| 14 | Three divergent section chunkers, one of them non-idempotent. `apply_chunking.py` omits `version`, so those rows are unsearchable behind the RPC's `bs.version` filter. | `scripts/ingest_esv.py:153-180`, `scripts/ingest_esv_sections.py:78-83`, `scripts/apply_chunking.py:92-102`; plain `insert` at `ingest_esv_sections.py:94-103`; upload omits `version` at `apply_chunking.py:113-117`; RPC filter `schema_update.py:25` | One chunker module; idempotent upsert keyed on version, book, chapter, range | OPEN |
| 15 | Schema and the search RPC exist only as a Python string run over SSH. Errors are printed and ignored, then the script exits 0. A helper truncates `bible_sections` with no confirmation. | `scripts/schema_update.py:18-25,35-47`; `scripts/remote_sql_exec.py:18` | Versioned migrations; fail on stderr; drop the truncate helper | OPEN |
| 16 | Error handling leaks internals and uses one status code. | `detail=str(e)` at `main.py:154,197,239,269,280` | Log the detail; return stable error codes and a request id | OPEN |

## Operations

| # | Finding | Evidence | Smallest fix | Status |
|---|---|---|---|---|
| 17 | The image runs an interpreter the project does not support. | `Dockerfile:1` is `python:3.12-slim`; `pyproject.toml:6` requires `>=3.13`. `uv pip compile --python-version 3.12` resolves without error, so the build succeeds and production runs 3.12. | Pin 3.13, copy `uv.lock`, install with `--frozen` | OPEN |
| 18 | The image is root, has no healthcheck, and bakes secrets in. | `Dockerfile:15` installs without the lockfile; no `USER`, no `HEALTHCHECK`; no `.dockerignore`; `COPY . .` at `:18` includes `.env` | Slim/multi-stage install, non-root user, `.dockerignore`, `HEALTHCHECK` against `/health` | OPEN |
| 19 | Deploy stops production before starting the replacement, with no rollback and no concurrency guard. Every push deploys, docs included. | `.github/workflows/deploy.yml:24-34` | Tag the running image, start on a second port, health check, switch; add `concurrency` and a path filter | OPEN |
| 20 | ESV credentials travel over unverified TLS. | `scripts/extract_pericopes.py:24,36,44` pins a raw IP, spoofs `Host`, and sets `verify=False` with warnings suppressed | Use `api.esv.org` with normal verification | OPEN |
| 21 | Paid endpoints have no auth or rate limit, and every origin is allowed. CORS itself is valid: Starlette echoes the origin with `Allow-Credentials: true`, which browsers accept. | `main.py:44-49`; `/api/chat/stream` and both search routes are unauthenticated | Drop credentials or list origins; add an API key or per-IP limit | OPEN |
| 22 | `/health` reports healthy with Supabase down. | `main.py:283-285` returns a constant | Add a readiness check that runs one cheap query | OPEN |

## Tests and logs

| # | Finding | Evidence | Smallest fix | Status |
|---|---|---|---|---|
| 23 | No route is exercised by any test. Coverage is pure helpers only. | No `TestClient` in the repo; `tests/test_unit_main.py:13-68` | Route tests for multi-version shape, 404, bad version, truncation flag | OPEN |
| 24 | Several tests pin wording and private helpers. | `tests/test_unit_agent.py:69-100` asserts prompt strings and the history window; `:99` asserts `len(msgs) == 12` | Keep `extract_citations` and tool-result shape tests; delete the wording pins | OPEN |
| 25 | The pytest config hides future integration tests. | `pyproject.toml:28` collects only `test_unit_*.py` | Widen the pattern when the first route test lands | OPEN |
| 26 | Full sermon payloads and query strings go to INFO logs. | `main.py:264`; request middleware `:55-60` | Log counts and ids, not content | OPEN |

## Proposed module shape

| Module | Owns |
|---|---|
| `config.py` | settings, one model id, thresholds, limits, validated at startup |
| `retrieval.py` | version resolution, book mapping, both queries, license cap, copyright. No FastAPI imports |
| `agent.py` | prompt construction and the tool loop. Takes version and retrieval as arguments; holds no request state |
| `main.py` | validation at the edge, envelope responses, error mapping |
| `sections.py` | the one pericope chunker and the idempotent upsert, used by all three scripts |

## Order of work

Each step ends in a check.

1. Thread the version through `run_stream` and the tools; delete `current_version`. Check: the two-stream repro passes with matching version filters. **Done in working tree; `tests/test_unit_agent.py::TestRunStreamConcurrency` covers it.**
2. Enum the version parameter, filter rows by requested version, return the envelope with `truncated`. Check: route tests for `?version=all`, `?version=bogus`, and a 600-row chapter. **Done in working tree; `tests/test_unit_routes.py` covers all three.**
3. Move retrieval into one module; delete the two query builders and the duplicate embedding/threshold sites. Check: existing unit tests plus one route test per endpoint.
4. Collapse the chunkers into one idempotent upsert; rebuild the mislabeled ESV sections. Check: a section title matches its verse range for Nahum 1. Code side is fixed in `e126fb6`; the data rebuild is not run.
5. Fix the async boundary: threadpool routes, threaded stream. Check: two concurrent chats and a `/health` call finish together.
6. Deploy hygiene: Python 3.13, lockfile, non-root, `.dockerignore`, healthcheck, rollback image tag. Check: `docker run` health status is healthy; a failed deploy leaves the old container serving.
7. Move schema into migrations. Check: a fresh database reaches searchable state without SSH.

Steps 1 and 2 change behavior users see.

## Verification basis

Measured during the audit: the version race (two threads, fake client, RPC observed `version_filter`), the grouping loss (`group_by_version` on lowercase and NULL versions), version passthrough, Starlette's CORS source in `.venv`, `uv pip compile` under 3.12 and 3.13, and `./bin/bible --help`.

Read from code and quoted above: everything else. Not built or deployed during the audit: the Docker image and workflows. No production database was touched, so row counts and the `content NOT NULL` question are unverified.

## Not audited

- `cli/render.py` and `cli/parser.py` internals beyond the duplicate reference parsers.
- `books.py` data correctness and the `pericope_map.json` structure.
- README accuracy against code.
- The ESV gap analysis from 2026-10-29 (response envelope, `q` resolver, search totals, books endpoint, auth, citations) is a separate contract roadmap, not this refactor list, and is not persisted.

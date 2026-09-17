# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Agentic Patterns Lab: a public demo site showcasing several Python AI agents, each built
to demonstrate a specific agentic pattern (prompt chaining, orchestrator-workers,
routing, parallelization, RAG, MCP). The code is public, so it is read by humans as
much as it is run.

The full spec lives in `docs/` (six numbered files, meant to be read as one set).
It is committed so the project can be picked up from any machine. Consult it
before making architectural decisions; it is the source of truth for contracts
and schemas.

Keep `docs/` and this file current. Whenever a decision made in a session changes
a contract, schema, config, architecture choice, build phase, or convention,
update the affected doc (and this file, if it touches anything described here)
in the same session, before the work is considered done. If a decision
contradicts the spec, change the spec rather than leaving the two out of sync.
Mention in the summary which docs were updated so Andres can review and commit
them.

## Division of work

- Claude builds the frontend UI and all non-agent backend code: FastAPI app and
  routes, rate limiter, LLM gateway, SSE transport, Postgres/Redis data layer,
  narrator plumbing, deployment config.
- Andres builds the AI agents: the LangGraph graphs (Research, Financial), the
  MCP finance server, and the prompts. Do not hand him finished code for those
  parts; act as a reviewer and pair on the design. Leave clearly marked
  seams where his agent code plugs into the infrastructure, explain the pattern
  and the trade-offs, and let him write the graph internals.
- Andres is the only one who commits. Never run `git commit` or `git push`.

## Conventions

- No emojis or icons in documentation, READMEs, or comments unless explicitly
  requested.
- Agents never call a provider SDK directly. Every LLM call goes through
  `gateway.complete(task=..., messages=[...])` so budget checks, provider
  fallback, and Langfuse tracing happen in exactly one place.
- The rate limiter and the per-provider budget tracker are two independent cost
  safety nets. Do not merge them.
- Never forward a raw provider error or stack trace to the frontend. Map known
  failure modes to `{"error": "<short_code>", "message": "<safe text>"}` before
  the response reaches the API boundary.
- Configurable values (rate limits, routing policy, daily budgets) live in config
  files, not inline in code.

## Architecture

Two deployments, deliberately split:

- `frontend/` — Next.js App Router + TypeScript + Tailwind, on Vercel. Reads
  `NEXT_PUBLIC_BACKEND_URL`.
- `backend/` — FastAPI + Python 3.13 + LangGraph, on Railway. Serverless does not
  handle long-lived streaming agent runs well, hence the separate host.
- `mcp_finance_server/` — standalone MCP server (Python `mcp` SDK, yfinance),
  consumed by the Financial agent as an MCP client.

Request path: browser to `POST /agents/{id}/run` (returns `run_id` immediately)
to `GET /agents/{id}/stream/{run_id}` (SSE). The rate limiter runs before the
router or any agent graph, so a 429 costs nothing. The agent graph emits typed
SSE events as it runs; the frontend routes each event to either the output panel
(`partial_output`, `run_complete`) or the narrator widget (`node_start`,
`tool_call`, `tool_result`, `rag_retrieval`, `fallback_triggered`, `node_end`,
`router_decision`). Event schema and `run_complete` shapes: `docs/03_API_CONTRACTS.md`.

The narrator is templated by default: LangGraph events map to sentences through a
lookup table with no LLM call. Only the on-demand Q&A mode spends tokens. Keep it
that way; an always-on explainer must not become the largest cost in the app.

Persistence: one Postgres instance holds `provider_spend` (daily budget state),
`call_logs` (per-call cost/latency), and `rag_documents` (pgvector, scoped per
`run_id` and disposable after a run). Redis (Upstash) holds only rate limit
counters, incremented atomically with a TTL. Schemas: `docs/04_DATA_MODELS.md`.

## Build order

`docs/05_BUILD_ROADMAP.md` defines six phases, each ending in something runnable
and deployed. Phase 1 is a skeleton with the safety nets and an echo agent,
deployed end to end before any real agent logic exists. Do not skip ahead;
the deployment path is proven first on purpose.

## Commands

Backend, from `backend/` (virtualenv at `backend/.venv`, Python 3.13). Andres
works on both Windows and macOS; the venv interpreter is `.venv/Scripts/python.exe`
on Windows and `.venv/bin/python` on macOS. Setup:

    py -3.13 -m venv .venv            # Windows
    python3.13 -m venv .venv          # macOS
    <venv python> -m pip install -r requirements.txt

Run and check (Windows paths shown; use `.venv/bin/python` on macOS):

    .venv/Scripts/python.exe -m uvicorn app.main:app --reload
    .venv/Scripts/python.exe tests/test_phase1.py

Frontend, from `frontend/`:

    npm run dev
    npm run build

`tests/test_phase1.py` is a plain assert script, not pytest: it stubs the gateway
and the rate limiter so it needs no network, database, or API key. Keep new
checks in that shape unless a real test framework earns its place.

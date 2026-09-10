# Agentic Patterns Lab

A public demo site showcasing AI agents built in Python, each chosen to
demonstrate a specific agentic pattern: prompt chaining, orchestrator-workers,
routing, parallelization, RAG, and MCP.

The frontend is a Next.js app on Vercel. The backend is a FastAPI service on
Railway, because agent orchestration needs a long-lived process with real
streaming rather than a serverless function.

## Status

Phases 1 and 2 are complete: the request path runs end to end with one echo
agent, across three providers with budget-aware fallback and Langfuse tracing.

| Piece | State |
|-------|-------|
| FastAPI app, health check, agent listing | done |
| Rate limiter, Upstash Redis, per-agent config | done |
| LLM gateway, budget check, fallback, cost accounting | done |
| Postgres schema, spend and call logs | done |
| SSE transport, event contract, safe error mapping | done |
| Echo agent | done |
| Next.js page with streaming output and quota badge | done |
| Langfuse tracing, OpenAI and Groq in the fallback chain | done |
| Research agent, RAG | Phase 3 |
| Narrator | Phase 4 |
| Financial agent, MCP finance server | Phase 5 |

## Running it locally

Backend, from `backend/`:

    py -3.13 -m venv .venv
    .venv/Scripts/python.exe -m pip install -r requirements.txt
    cp .env.example .env          # set ANTHROPIC_API_KEY at minimum
    .venv/Scripts/python.exe -m uvicorn app.main:app --reload

Frontend, from `frontend/`:

    npm install
    cp .env.local.example .env.local
    npm run dev

Postgres and Redis are optional locally: without them the budget check passes
and the rate limiter is open, each logging a warning at startup.

## Checks

    cd backend && .venv/Scripts/python.exe tests/test_phase1.py
    cd frontend && npm run build

## Deploying

Railway serves `backend/` using the `Procfile`; set the variables from
`backend/.env.example` plus `CORS_ORIGINS` pointing at the Vercel domain.
Vercel serves `frontend/` with root directory `frontend` and
`NEXT_PUBLIC_BACKEND_URL` pointing at the Railway domain.

## Rehearsing a fallback

Set `DAILY_BUDGET_ANTHROPIC_USD=0` and run the echo agent. The gateway skips
Anthropic, emits a `fallback_triggered` event naming the reason, and answers
from OpenAI instead. This works with no database, because an unset
`DATABASE_URL` reports today's spend as zero and zero already meets a zero cap.

## Cost safety

Two independent nets. The rate limiter caps how many runs one IP may start per
agent per day and rejects the request before any model call happens. The gateway
caps how much money each provider may be given per day, checked before every
call and updated from real token usage afterwards.

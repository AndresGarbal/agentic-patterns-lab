# Backend

FastAPI service for Agentic Patterns Lab. Runs the agent graphs, enforces the rate
limit and the provider budget, and streams events to the frontend over SSE.

## Local development

    py -3.13 -m venv .venv
    .venv/Scripts/python.exe -m pip install -r requirements.txt
    cp .env.example .env          # set ANTHROPIC_API_KEY at minimum
    .venv/Scripts/python.exe -m uvicorn app.main:app --reload

Postgres and Redis are optional locally. With `DATABASE_URL` unset the budget
check passes and calls are not logged; with the Upstash variables unset the rate
limiter is open. Both log a warning at startup so the degraded state is visible.

## Checks

    .venv/Scripts/python.exe tests/test_phase1.py

Stubs the gateway and the rate limiter, so it needs no network, database, or
API key.

## Providers

`config.py` holds the model catalogue and the routing policy: a task type maps
to an ordered list of models, and the gateway walks that list, skipping any
model whose API key is unset or whose provider is over its daily budget, then
falling through on a provider error. A skip for a missing key is silent; a skip
for budget or an error emits a `fallback_triggered` event so the narrator can
show it. Prices live in the catalogue too, so spend is computed from real token
usage rather than from litellm's cost map.

Langfuse is registered once at startup as a litellm callback. Every gateway call
is traced with the run id, and tagged with the agent id and task type, with no
per-agent instrumentation.

## Layout

| File | Responsibility |
|------|----------------|
| `app/config.py` | Rate limits, model catalogue, routing policy, budgets |
| `app/rate_limit.py` | Per-IP daily caps via Upstash Redis |
| `app/gateway.py` | The only place that calls an LLM provider |
| `app/db.py` | Postgres pool, spend accounting, call logs |
| `app/agents.py` | Agent registry |
| `app/main.py` | Routes, SSE transport, error mapping |

## Adding an agent

An agent is an async generator that takes `(run_id, payload)` and yields event
dicts matching `docs/03_API_CONTRACTS.md`, ending with `run_complete`. Register
it in `AGENT_RUNNERS` in `app/agents.py` and add its id to `AGENTS` and
`RATE_LIMITS` in `app/config.py`. Call models only through
`gateway.stream(...)` or `gateway.complete(...)`; forward the events the gateway
yields so provider fallbacks show up in the narrator.

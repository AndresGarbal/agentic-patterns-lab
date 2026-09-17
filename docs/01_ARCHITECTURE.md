# Architecture

## Component list

| Component        | Responsibility                                                   | Host          |
|-------------------|-------------------------------------------------------------------|---------------|
| Frontend           | Landing page, per-agent pages, narrator widget                    | Vercel        |
| Backend API         | FastAPI app, LangGraph agent graphs, SSE streaming                | Railway       |
| Router              | Classifies an incoming request, picks an agent lane               | Backend       |
| Rate limiter        | Per-IP request caps, checked before any LLM call is made          | Backend + Upstash Redis |
| LLM gateway         | Provider routing policy, budget tracking, automatic fallback      | Backend (LiteLLM) |
| Research agent      | Planner/Researcher/Critic/Writer LangGraph graph, RAG over pgvector | Backend    |
| Financial agent     | Compute + parallel self-verification LangGraph graph, MCP client  | Backend       |
| MCP finance server  | Exposes finance data tools over MCP                               | Railway (own process) or same service |
| Narrator engine     | Turns the LangGraph event trace into plain-English commentary     | Backend       |
| Observability        | Traces and cost, fed by the gateway                               | Langfuse Cloud (free tier) |
| Postgres             | Provider budget state, call logs, pgvector documents              | Railway managed Postgres |
| Redis                | Rate limit counters                                                | Upstash (free tier) |

## Data flow (summary)

1. Browser loads the Next.js app from Vercel.
2. User submits a request on an agent page. Frontend calls the backend REST
   endpoint for that agent (or a generic `/run` endpoint if the router is
   meant to pick the agent automatically - see `03_API_CONTRACTS.md`).
3. Backend checks the rate limiter first. If the IP is over its cap, return
   429 immediately, no LLM call is made.
4. Router (if used) classifies the request.
5. The chosen agent graph runs. Every LLM call inside it goes through the
   gateway, which checks the per-provider budget, picks a provider per the
   routing policy, and falls back to the next provider on error or budget
   exhaustion.
6. Every gateway call is also reported to Langfuse via the LiteLLM callback.
7. As the graph runs, it emits structured events over SSE. The frontend's
   narrator widget consumes this stream and renders commentary live.
8. The final result streams back to the agent page's output panel.

## Tech stack

| Layer            | Choice                          | Notes |
|--------------------|----------------------------------|-------|
| Frontend framework  | Next.js (App Router), TypeScript, Tailwind | Deployed on Vercel |
| Backend framework   | FastAPI, Python 3.13             | Deployed on Railway |
| Agent orchestration | LangGraph                        | State graphs per agent |
| LLM gateway         | LiteLLM (Router)                 | Unified client, fallback chains, budget hooks |
| LLM providers       | Anthropic (Claude), OpenAI (GPT-4o-mini), Groq | Routed by task type, see `02_MODULE_REQUIREMENTS.md` |
| Vector store        | Postgres + pgvector extension    | Same database as everything else, no separate service |
| Relational store    | Postgres (Railway managed)       | Budgets, call logs |
| Rate limit store    | Redis (Upstash, serverless-friendly) | Atomic INCR with TTL |
| Observability       | Langfuse Cloud (free tier)       | Fed automatically via LiteLLM callback |
| MCP server          | Python `mcp` SDK                 | Exposes finance tools |
| Streaming transport | Server-Sent Events (SSE)         | Simpler than WebSockets for one-directional agent-to-UI updates |

## Hosting and environment variables

### Vercel (frontend)
```
NEXT_PUBLIC_BACKEND_URL=https://<railway-app>.up.railway.app
```

### Railway (backend)
```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GROQ_API_KEY=
DATABASE_URL=                 (Railway Postgres, pgvector enabled)
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
TAVILY_API_KEY=                (or Firecrawl, for the Researcher's web search tool)
MCP_FINANCE_SERVER_URL=        (if run as a separate process/service)
```

### Cost safety defaults (override in the rate limit config file, not in code)
```
DAILY_BUDGET_ANTHROPIC_USD=2.00
DAILY_BUDGET_OPENAI_USD=2.00
DAILY_BUDGET_GROQ_USD=1.00
```

These are starting points - exact per-agent request caps are decided
separately, see the rate limiter config in `02_MODULE_REQUIREMENTS.md`.

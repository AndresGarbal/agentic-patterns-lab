# Agentic Patterns Lab - Project Overview

## What this is

A public demo site showcasing multiple AI agents built in Python, deployed for
free/low cost. Every agent is picked and built to demonstrate a specific,
recognizable agentic pattern - not just "a chatbot with an API key."

## Who built what

The AI agents are designed and written by Andres Garcia: the LangGraph graphs
(Research, Financial), the MCP finance server, and the prompts. The supporting
infrastructure (FastAPI routes, rate limiter, LLM gateway, SSE transport, data
layer, deployment config) and the frontend were built with Claude Code.

## Patterns demonstrated (and where)

| Pattern               | Where it lives                                          |
|------------------------|---------------------------------------------------------|
| Prompt chaining        | Research agent (Planner to Researcher to Writer) and Financial agent (compute to verify) |
| Orchestrator-workers   | Research agent's Planner dynamically assigns work to Researcher/Critic/Writer |
| Routing                | Front-door classifier that sends a request to the right agent lane |
| Parallelization        | Researcher fires sub-queries concurrently (sectioning); Financial agent verifies its math against two providers concurrently (voting) |
| RAG                    | Researcher embeds fetched sources into pgvector; Critic and Writer retrieve from there instead of re-reading raw text |
| MCP                    | A custom MCP server exposes finance data tools; the Financial agent connects to it as an MCP client |

## Why this architecture (for anyone reviewing the code)

- Vercel hosts only the frontend. Python agent orchestration needs a
  long-lived process with real streaming, which serverless functions on
  Vercel do not handle well - so the backend lives on Railway instead. This
  split is deliberate, not incidental.
- A rate limiter and a per-provider budget tracker are two independent
  safety nets against surprise API cost, not one mechanism doing both jobs.
- Every LLM call goes through a single gateway module (LiteLLM-based) so
  provider fallback, budget checks, and Langfuse tracing all happen in one
  place instead of being duplicated per agent.
- The narrator agent is mostly deterministic templating over the LangGraph
  event trace, not a constant LLM call, specifically so an "always-on
  explainer" does not quietly become the most expensive part of the app.

## Repository structure (suggested)

```
agent-lab/
  frontend/                 Next.js app (Vercel)
    app/
      page.tsx               landing page
      research/page.tsx
      financial/page.tsx
      components/
        AgentRunner.tsx       shared input/output/streaming component
        NarratorWidget.tsx    floating narrator, lives in root layout
        layout.tsx
  backend/                  FastAPI + LangGraph (Railway)
    app/
      main.py                 FastAPI app, routes
      router/                 request classifier
      agents/
        research/              Planner/Researcher/Critic/Writer graph
        financial/              compute + verify graph
      gateway/                 LiteLLM wrapper, routing policy, budget tracker
      rate_limit/              Upstash Redis middleware
      narrator/                event-to-template engine + optional LLM Q&A
      rag/                     pgvector embed/retrieve helpers
      observability/           Langfuse wiring
    mcp_finance_server/       standalone MCP server (own repo or subfolder)
  docs/                      this folder
```

## Documents in this set

1. `01_ARCHITECTURE.md` - components, tech stack, hosting, environment variables
2. `02_MODULE_REQUIREMENTS.md` - detailed spec per module
3. `03_API_CONTRACTS.md` - REST and SSE contracts between frontend and backend
4. `04_DATA_MODELS.md` - Postgres schema, pgvector schema, Redis key patterns
5. `05_BUILD_ROADMAP.md` - suggested build order in phases

Hand all of them to Claude Code together - they are meant to be read as one set.

# Module Requirements

Each section below is meant to be readable on its own - Claude Code can be
pointed at one section at a time when building that piece.

---

## 1. Frontend (Next.js on Vercel)

### Purpose
Serve the landing page, the per-agent pages, and the always-on narrator
widget. Talk to the backend over REST for triggering a run and over SSE for
streaming both the result and the narrator's live commentary.

### Functional requirements
- Landing page: one card per agent, each stating the agent's name, a one
  line description, and the pattern(s) it demonstrates.
- One route per agent (`/research`, `/financial`, more added later).
- Each agent page shares one `AgentRunner` component: input field(s)
  specific to that agent, a submit button, a "calls remaining today" badge,
  and a streaming output panel.
- Narrator widget lives in the root layout (not per-page), so it persists
  across navigation. Open by default on first visit. Collapsible. State
  (open/closed) remembered in `sessionStorage` equivalent - since this is a
  hosted app (not a claude.ai artifact), real `localStorage` is fine here.
- Narrator shows an idle message when no agent is running, and switches to
  live commentary the moment an agent starts.
- On a 429 response, show the rate limit message returned by the backend,
  not a generic error.

### Non-functional requirements
- No authentication - public demo, IP-based limiting only.
- Must degrade gracefully if the backend is unreachable (show a clear
  "backend is waking up or unavailable" state, since Railway free tier can
  cold-start).

---

## 2. Rate limiter

### Purpose
The first safety net against surprise cost - stop a request before any LLM
call happens, based on IP and agent.

### Functional requirements
- Sliding or fixed window counter, keyed by `f"{ip}:{agent_id}:{date}"`.
- Backed by Upstash Redis, atomic increment with TTL (do not read-then-write,
  race conditions under concurrent requests would let the limit slip).
- Limits are defined in a config file (not hardcoded), one entry per agent,
  so exact numbers can be tuned without a code change:
  ```
  RATE_LIMITS = {
      "research": {"calls_per_day": 5},
      "financial": {"calls_per_day": 5},
  }
  ```
- On limit exceeded, return HTTP 429 with a JSON body:
  ```
  {"error": "rate_limited", "agent": "research", "retry_after_seconds": N,
   "message": "Daily demo limit reached for this agent. Try again tomorrow."}
  ```
- Applied as FastAPI middleware or a dependency, checked before the request
  reaches the router or any agent graph.

---

## 3. LLM gateway

### Purpose
Single point through which every LLM call passes - handles provider choice,
budget enforcement, and fallback. This is the "do not get surprised by
provider cost" guarantee, independent of the rate limiter.

### Functional requirements
- Built on LiteLLM's `Router`, configured with a named model list for each
  provider (Anthropic, OpenAI, Groq).
- Task-to-provider policy (config, not hardcoded):
  ```
  ROUTING_POLICY = {
      "narrator":            ["groq/llama-3.1-8b", "claude-haiku"],
      "planning":            ["claude-haiku", "gpt-4o-mini"],
      "structured_extract":  ["gpt-4o-mini", "claude-haiku"],
      "verification":        ["claude-haiku", "gpt-4o-mini"],  # called twice in parallel, see Financial agent
  }
  ```
- Before each call, check the current day's spend for the selected provider
  against its budget cap (stored in Postgres, see `04_DATA_MODELS.md`). If
  over budget, skip to the next provider in that task's list. If all
  providers in the list are over budget, return a clear error the agent can
  surface, do not fail silently.
- After each call, record actual token usage and cost (from the provider's
  response) into the `provider_spend` table.
- Register the Langfuse callback so every call is traced automatically:
  ```python
  import litellm
  litellm.success_callback = ["langfuse"]
  litellm.failure_callback = ["langfuse"]
  ```
- Fallback also triggers on provider error or timeout, not only budget.

### Non-functional requirements
- This module must be provider-agnostic in its interface - agents call
  `gateway.complete(task="planning", messages=[...])`, never a provider SDK
  directly.

---

## 4. Router (classifier)

### Purpose
Demonstrates the routing pattern: reads an incoming request and decides
which agent lane should handle it (useful now, and necessary once a third
or fourth agent is added and the landing page offers a single "just ask"
box in addition to the two dedicated agent pages).

### Functional requirements
- Single cheap LLM call (Groq, task type `"routing"` in the gateway policy)
  that classifies the request into one of the known agent ids.
- If the frontend already knows which agent page the user is on, the router
  can be skipped (the request already declares its target agent) - the
  router matters most for a future "single input, any agent" entry point.
- Emits a narrator event either way (`"router_decision"`) so the pattern is
  visibly demonstrated even when the frontend already knows the target.

---

## 5. Research agent (LangGraph)

### Purpose
Demonstrates prompt chaining, orchestrator-workers, parallelization, and RAG
in one agent.

### Graph structure
```
Planner -> Researcher (parallel sub-queries) -> Critic -> Writer
                                     ^                |
                                     +---- loop back -+  (if Critic rejects sources)
```

### Functional requirements
- **Planner** node: breaks the user's question into 3-5 sub-questions.
  Gateway task type: `"planning"`.
- **Researcher** node: runs all sub-questions concurrently with
  `asyncio.gather`, each sub-question hitting the web search tool
  (Tavily or Firecrawl). This is the parallelization (sectioning) pattern.
- After fetching, each source is chunked, embedded, and upserted into the
  `rag_documents` table (pgvector). Raw scraped text is not kept in the
  LangGraph state past this point - only embeddings and short metadata are.
- **Critic** node: retrieves the top-k relevant chunks from pgvector (RAG)
  for each sub-question, checks source quality/relevance, and either
  approves or sends specific sub-questions back to the Researcher for a
  second pass (max one retry per sub-question, to bound cost).
- **Writer** node: retrieves from pgvector again (RAG) and composes the
  final report with inline citations back to source URLs.
- Emits narrator events at every node transition and every tool call.

---

## 6. Financial agent (LangGraph)

### Purpose
Demonstrates prompt chaining, parallelization (as a voting/consensus check
rather than sectioning), and MCP as a client.

### Graph structure
```
Interpreter -> Compute (via MCP tools) -> Verify (parallel, 2 providers) -> Answer
```

### Functional requirements
- **Interpreter** node: parses the user's question into a structured request
  (ticker, metric, time range). Gateway task type: `"structured_extract"`.
- **Compute** node: calls the MCP finance server's tools (see section 7) to
  fetch the underlying data, then executes the actual calculation in a
  sandboxed Python tool call rather than asking the LLM to do arithmetic.
- **Verify** node: sends the computed result and its reasoning to two
  providers concurrently (gateway task type `"verification"`, which lists
  two providers) and compares their agreement. If they disagree
  meaningfully, flag it in the final answer rather than silently picking
  one.
- **Answer** node: formats the final response, including the chart data for
  the frontend to render.
- Emits narrator events at every node transition and every MCP tool call.

---

## 7. MCP finance server

### Purpose
A standalone MCP server exposing finance data tools, consumed by the
Financial agent as an MCP client. It is also self-contained, so it can be linked to and explained
independently of the demo app.

### Functional requirements
- Built with the Python `mcp` SDK.
- Tools exposed:
  - `get_stock_price(ticker: str, date: str | None) -> dict`
  - `get_financials(ticker: str, period: str) -> dict`
  - `get_news_sentiment(ticker: str, days: int) -> dict`
- Backed by yfinance for price/financials data; a news API (or a simple
  headline scrape plus sentiment classification call) for sentiment.
- Runs as its own process. In development, run alongside the backend; in
  production, either as a second Railway service or as a subprocess the
  backend spawns and connects to over stdio - pick whichever is simpler to
  deploy reliably, note the choice in the README once decided.
- Cache tool results briefly (a few minutes) to avoid redundant external API
  calls within a burst of user activity.

---

## 8. Narrator engine

### Purpose
Always-on explainer that narrates what the active agent is doing, without
becoming a meaningful cost center itself.

### Functional requirements
- Two modes:
  1. **Templated (default, no LLM call)**: every LangGraph event (node
     entered, tool called, tool result received, node finished, fallback
     triggered, RAG retrieval performed) maps to a plain-English sentence
     via a lookup table, e.g. `tool_call:web_search -> "Researcher is
     searching the web for: {query}"`. This is what runs on every single
     agent execution, at effectively zero cost.
  2. **Interactive Q&A (on demand, does use an LLM call)**: if the user
     asks the narrator a direct question ("why did it do that?"), that
     single question goes through the gateway with task type `"narrator"`
     (routed to Groq first, cheapest/fastest), with the recent event trace
     as context.
- Streams over the same SSE connection as the agent's own output, tagged
  with a distinct event type so the frontend can route templated narration
  vs interactive answers to the right place in the widget.

---

## 9. Observability (Langfuse)

### Purpose
Traces every gateway call automatically, plus gives you a cost dashboard
without building one from scratch.

### Functional requirements
- Langfuse Cloud free tier, one project for the whole app.
- LiteLLM success/failure callbacks registered globally in the gateway
  module (see section 3) - no manual instrumentation needed per agent.
- Tag each trace with `agent_id` and `task_type` metadata so the Langfuse
  dashboard can be filtered per agent.
- Optional stretch: a small `/stats` endpoint in the backend that reads
  aggregated numbers back out (via Langfuse's API or directly from the
  `provider_spend` Postgres table) to show on an "about this project" page,
  even though Langfuse's own UI already covers it.

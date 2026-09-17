# Build Roadmap

Suggested order - each phase produces something runnable before moving to
the next, so the project is never in a broken state for long.

## Phase 1 - Skeleton and safety nets
- FastAPI app with a health check endpoint.
- Rate limiter middleware wired to Upstash Redis, config file with initial
  conservative limits (e.g. 5 calls/day/agent).
- LLM gateway module wired to LiteLLM with one provider only (Anthropic) to
  start - fallback chain and the other two providers come in Phase 2.
- Postgres schema created (`provider_spend`, `call_logs`; `rag_documents`
  can wait until Phase 3).
- A single trivial "echo" agent (no LangGraph yet) to prove the whole
  request -> rate limiter -> gateway -> response path works end to end,
  deployed to Railway.
- Minimal Next.js app deployed to Vercel, one page that calls the echo
  agent - proves the cross-origin, cross-host deployment works before any
  real agent logic exists.

## Phase 2 - LLM gateway completed
- Add OpenAI and Groq to the LiteLLM router.
- Implement the full routing policy and budget check against
  `provider_spend`.
- Add Langfuse callback (`success_callback` / `failure_callback`).
- Manually trigger a fallback (e.g. temporarily set a provider's budget to
  0) and confirm it falls through correctly and shows up in Langfuse.

## Phase 3 - Research agent
- Build the LangGraph graph: Planner -> Researcher -> Critic -> Writer.
- Wire the Researcher's web search tool (Tavily or Firecrawl).
- Add `rag_documents` table, embed sources, retrieve in Critic/Writer.
- Add SSE event emission at each node transition and tool call.
- Build the `/research` frontend page and shared `AgentRunner` component.

## Phase 4 - Narrator (templated mode first)
- Build the event-to-sentence template engine, wire it to the same SSE
  stream as the Research agent.
- Build the floating narrator widget in the frontend root layout, open by
  default, collapsible.
- Confirm it renders live commentary while the Research agent runs, with
  no additional LLM calls yet (Q&A mode comes later, it is optional
  polish).

## Phase 5 - Financial agent and MCP
- Build the MCP finance server as its own small project, test it
  standalone with an MCP client/inspector before wiring it into the agent.
- Build the Financial agent's LangGraph graph: Interpreter -> Compute
  (via MCP) -> Verify (parallel, two providers) -> Answer.
- Build the `/financial` frontend page.
- Confirm the narrator also renders sensible commentary for this agent's
  event types (MCP tool calls in particular).

## Phase 6 - Polish and deploy
- Narrator's interactive Q&A mode (on-demand LLM call).
- Landing page final copy, agent cards with pattern labels.
- `/stats` endpoint and a small dashboard section, if time allows, or rely
  on Langfuse's own dashboard as the primary source of truth for that.
- Final environment variable audit on both Vercel and Railway.
- Load-test the rate limiter with a quick script hitting the endpoint past
  the limit, confirm the 429 path works before making the link public.

## What to add later (not in the initial build)
- A third agent, to keep demonstrating the pattern-per-agent structure.
- A second MCP touchpoint - consuming a hosted MCP server (e.g. Tavily's)
  instead of only providing one.
- Persisting `rag_documents` longer term with a cleanup job, if research
  runs should be revisitable rather than ephemeral.

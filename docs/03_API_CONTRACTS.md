# API Contracts

All endpoints are served by the FastAPI backend. The frontend never calls
an LLM provider or the MCP server directly.

## REST endpoints

### `GET /agents`
Returns the list of available agents, for the landing page to render
without hardcoding it on the frontend.

Response:
```json
{
  "agents": [
    {
      "id": "research",
      "name": "Research agent",
      "description": "Plans, searches in parallel, and writes a cited report.",
      "patterns": ["prompt chaining", "orchestrator-workers", "parallelization", "rag"]
    },
    {
      "id": "financial",
      "name": "Financial agent",
      "description": "Computes and cross-checks financial answers using live data.",
      "patterns": ["prompt chaining", "parallelization", "mcp"]
    }
  ]
}
```

### `GET /rate-limit/status?agent_id=research`
Frontend calls this on page load to show the remaining-calls badge before
the user submits anything.

Response:
```json
{"agent_id": "research", "calls_used": 1, "calls_limit": 5, "resets_at": "2026-08-22T00:00:00Z"}
```

### `POST /agents/{agent_id}/run`
Starts a run. Returns a `run_id` immediately; the actual work streams over
SSE (see below). Kept separate from the SSE endpoint so the frontend can
show "starting..." before the stream connects.

Request:
```json
{"input": {"question": "How did NVDA's data center revenue trend this year?"}}
```

Response (202 Accepted):
```json
{"run_id": "a1b2c3"}
```

Response on rate limit (429):
```json
{"error": "rate_limited", "agent": "research", "retry_after_seconds": 41000,
 "message": "Daily demo limit reached for this agent. Try again tomorrow."}
```

### `GET /agents/{agent_id}/stream/{run_id}` (SSE)
The frontend opens this immediately after receiving `run_id`. Emits a
sequence of events (see event schema below) and closes when the run
completes or errors.

---

## SSE event schema

Every event is a JSON object with at least `type` and `run_id`. The
frontend routes events to either the output panel or the narrator widget
based on `type`.

| type              | Consumed by      | Payload fields                          |
|--------------------|-------------------|------------------------------------------|
| `node_start`         | Narrator          | `node`, `label`                           |
| `tool_call`           | Narrator          | `node`, `tool`, `args_summary`            |
| `tool_result`         | Narrator          | `node`, `tool`, `result_summary`          |
| `rag_retrieval`       | Narrator          | `node`, `k`, `query`                      |
| `fallback_triggered`  | Narrator          | `from_provider`, `to_provider`, `reason`  |
| `node_end`            | Narrator          | `node`                                    |
| `router_decision`     | Narrator          | `chosen_agent`, `reason_summary`          |
| `partial_output`      | Output panel      | `text` (streamed chunks of the final answer) |
| `run_complete`        | Output panel      | `result` (full structured result, see per-agent shape below) |
| `error`               | Both              | `message`                                 |

### `run_complete` result shape - research agent
```json
{
  "report_markdown": "...",
  "sources": [{"url": "...", "title": "..."}]
}
```

### `run_complete` result shape - financial agent
```json
{
  "answer_markdown": "...",
  "chart_data": {"labels": ["Q1", "Q2", "Q3", "Q4"], "values": [1.2, 1.4, 1.3, 1.6]},
  "verification": {"agreement": true, "providers_checked": ["claude-haiku", "gpt-4o-mini"]}
}
```

## Error format (all endpoints)

```json
{"error": "<short_code>", "message": "<human readable, safe to show in UI>"}
```

Never forward a raw provider or stack trace error to the frontend - map
known failure modes (rate limited, all providers over budget, MCP server
unreachable, upstream provider error) to a short code and a clear message
in the gateway/agent layer before the response reaches the API boundary.

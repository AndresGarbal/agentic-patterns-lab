# Data Models

## Postgres (Supabase, pgvector extension enabled)

### `provider_spend`
Tracks running daily spend per provider, checked by the gateway before every
call.

```sql
CREATE TABLE provider_spend (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,           -- 'anthropic' | 'openai' | 'groq'
    day DATE NOT NULL,
    spend_usd NUMERIC(14, 8) NOT NULL DEFAULT 0,
    UNIQUE (provider, day)
);
```
Updated with an upsert (`INSERT ... ON CONFLICT (provider, day) DO UPDATE
SET spend_usd = provider_spend.spend_usd + EXCLUDED.spend_usd`) after every
gateway call, using actual token usage and the provider's published
per-token price.

### `call_logs`
One row per LLM call, independent of what Langfuse also records - kept
locally so the backend can serve its own `/stats` endpoint without a round
trip to Langfuse's API.

```sql
CREATE TABLE call_logs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INT,
    output_tokens INT,
    cost_usd NUMERIC(14, 8),
    latency_ms INT,
    fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
    success BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_call_logs_agent ON call_logs (agent_id, created_at);
```

### `rag_documents`
Source chunks embedded by the Research agent's Researcher node, retrieved
by the Critic and Writer nodes.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE rag_documents (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,             -- scoped per run, not shared across users
    source_url TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(1536) NOT NULL,  -- text-embedding-3-small output size
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_rag_documents_run ON rag_documents (run_id);
```
There is deliberately no vector index. Every search filters by `run_id`, and
a run holds at most a few hundred chunks, so an exact scan over them is fast
and always correct. An approximate index (ivfflat) applies the `run_id` filter
after its own candidate search, which can return fewer than `k` rows. Revisit
only if searches ever span runs.
Rows can be deleted after a run completes, or kept with a TTL cleanup job -
this data does not need to persist across runs since each research question
is independent.

Writes go through `db.save_chunks(run_id, chunks)`, where each chunk is a dict
with `source_url`, `chunk_text` and `embedding` (a list of 1536 floats). The
`vector` type is mapped by the `pgvector` Python package: its codec is
registered on every pooled connection through the pool's `init` hook. That
hook needs the extension to exist, so `db.connect()` applies `schema.sql` on a
standalone connection before it creates the pool.

Reads go through `db.search_chunks(run_id, query_embedding, k)`, which returns
up to `k` dicts with `source_url`, `chunk_text` and `distance` (cosine
distance, `<=>`), closest first. With no database it returns an empty list,
so the Critic and Writer nodes must handle having no chunks.

---

## Redis (Upstash)

Used only for rate limiting - nothing else needs to live here.

Key pattern:
```
ratelimit:{agent_id}:{ip}:{date}   ->  integer counter, TTL until midnight UTC
```

Operations:
- `INCR` the key on every incoming request (before any LLM call).
- If the returned value is 1 (key was just created), set its expiry with
  `EXPIRE` to end of day.
- If the returned value exceeds the configured limit for that agent, return
  429 before proceeding.

This keeps the check to a single atomic Redis round trip per request.

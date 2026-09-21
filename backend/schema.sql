-- Applied on startup by app/db.py. Safe to run repeatedly.
-- rag_documents is not here; it arrives in Phase 3 with the Research agent.

CREATE TABLE IF NOT EXISTS provider_spend (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    day DATE NOT NULL,
    spend_usd NUMERIC(14, 8) NOT NULL DEFAULT 0,
    UNIQUE (provider, day)
);

CREATE TABLE IF NOT EXISTS call_logs (
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

CREATE INDEX IF NOT EXISTS idx_call_logs_agent ON call_logs (agent_id, created_at);

-- Widen the money columns on databases created before the precision fix. A
-- single call to a cheap model costs ~0.00002 USD, which rounded to 0.0000 at
-- the old NUMERIC(10, 4) scale, so the daily spend never moved off zero and the
-- budget cap never tripped. Both tables are small, so the rewrite is cheap.
ALTER TABLE provider_spend ALTER COLUMN spend_usd TYPE NUMERIC(14, 8);
ALTER TABLE call_logs ALTER COLUMN cost_usd TYPE NUMERIC(14, 8);

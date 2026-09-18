"""Postgres access. Every function no-ops when DATABASE_URL is unset, so the
app runs locally without a database."""
import datetime
import logging
import os
import pathlib

import asyncpg

log = logging.getLogger(__name__)
_pool: asyncpg.Pool | None = None
_SCHEMA = pathlib.Path(__file__).resolve().parent.parent / "schema.sql"


async def connect() -> None:
    global _pool
    url = os.getenv("DATABASE_URL")
    if not url:
        log.warning("DATABASE_URL unset: budget checks pass and calls are not logged")
        return
    try:
        _pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
        async with _pool.acquire() as conn:
            await conn.execute(_SCHEMA.read_text())
    except Exception:
        # A database that is misconfigured or down must not take the whole API
        # with it: degrade to the same no-op mode as an unset DATABASE_URL, and
        # make the reason loud in the logs.
        _pool = None
        log.exception("DATABASE_URL set but unusable: running without budget checks or call logs")


async def close() -> None:
    if _pool:
        await _pool.close()


async def spend_today(provider: str) -> float:
    if not _pool:
        return 0.0
    row = await _pool.fetchrow(
        "SELECT spend_usd FROM provider_spend WHERE provider = $1 AND day = $2",
        provider,
        datetime.datetime.now(datetime.UTC).date(),
    )
    return float(row["spend_usd"]) if row else 0.0


async def record_call(**call) -> None:
    """Add the call's cost to today's provider spend and log the call itself."""
    if not _pool:
        return
    async with _pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO provider_spend (provider, day, spend_usd) VALUES ($1, $2, $3)
               ON CONFLICT (provider, day)
               DO UPDATE SET spend_usd = provider_spend.spend_usd + EXCLUDED.spend_usd""",
            call["provider"],
            datetime.datetime.now(datetime.UTC).date(),
            call["cost_usd"],
        )
        await conn.execute(
            """INSERT INTO call_logs (run_id, agent_id, task_type, provider, model,
                   input_tokens, output_tokens, cost_usd, latency_ms, fallback_used, success)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
            call["run_id"],
            call["agent_id"],
            call["task_type"],
            call["provider"],
            call["model"],
            call["input_tokens"],
            call["output_tokens"],
            call["cost_usd"],
            call["latency_ms"],
            call["fallback_used"],
            call["success"],
        )

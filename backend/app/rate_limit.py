"""Per-IP, per-agent daily caps backed by Upstash Redis.

First cost safety net: it runs before the router and before any LLM call, so a
blocked request costs nothing. Disabled (open) when Upstash env vars are unset,
which only happens in local development.
"""
import datetime
import logging
import os

import httpx

from .config import RATE_LIMITS

log = logging.getLogger(__name__)
_client: httpx.AsyncClient | None = None


def _config() -> tuple[str, str] | None:
    url = os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    return (url.rstrip("/"), token) if url and token else None


async def startup() -> None:
    global _client
    if _config():
        _client = httpx.AsyncClient(timeout=5.0)
    else:
        log.warning("Upstash env unset: rate limiting is disabled")


async def shutdown() -> None:
    if _client:
        await _client.aclose()


def limit_for(agent_id: str) -> int:
    return RATE_LIMITS.get(agent_id, {}).get("calls_per_day", 5)


def resets_at() -> datetime.datetime:
    now = datetime.datetime.now(datetime.UTC)
    return (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def seconds_until_reset() -> int:
    return max(1, int((resets_at() - datetime.datetime.now(datetime.UTC)).total_seconds()))


def _key(agent_id: str, ip: str) -> str:
    day = datetime.datetime.now(datetime.UTC).date().isoformat()
    return f"ratelimit:{agent_id}:{ip}:{day}"


async def _pipeline(commands: list[list]) -> list:
    cfg = _config()
    if not cfg or not _client:
        return []
    url, token = cfg
    r = await _client.post(url + "/pipeline", json=commands, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return [step.get("result") for step in r.json()]


async def hit(agent_id: str, ip: str) -> int:
    """Atomically count this request. Returns the day's count so far, 0 if disabled."""
    key = _key(agent_id, ip)
    # INCR then EXPIRE NX in one round trip: the TTL is set only on creation, so
    # a later call in the same day cannot push the window forward.
    results = await _pipeline([["INCR", key], ["EXPIRE", key, seconds_until_reset(), "NX"]])
    return int(results[0]) if results else 0


async def used(agent_id: str, ip: str) -> int:
    """Read-only count, for the remaining-calls badge."""
    results = await _pipeline([["GET", _key(agent_id, ip)]])
    return int(results[0]) if results and results[0] is not None else 0

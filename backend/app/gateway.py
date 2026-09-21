"""The single door every LLM call goes through.

Agents call gateway.stream(...) or gateway.complete(...) with a task type and
never touch a provider SDK. Provider choice, the daily budget check, fallback,
cost accounting, and Langfuse tracing all live here so there is exactly one
place to change any of them.

Second cost safety net, independent of the rate limiter: the rate limiter caps
how many requests a visitor may make, this caps how much money the providers may
be given in a day.
"""
import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator

import litellm

from . import db
from .config import DAILY_BUDGET_USD, MAX_TOKENS, MODELS, ROUTING_POLICY

log = logging.getLogger(__name__)
litellm.suppress_debug_info = True
# Providers disagree on which optional params they accept (stream_options, for
# one). Dropping the unsupported ones beats maintaining a per-provider matrix.
litellm.drop_params = True

NO_KEY = "not configured"
OVER_BUDGET = "over daily budget"

_langfuse = None


class GatewayError(Exception):
    """Carries a short code and a message that is safe to show in the UI."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _NoSpan:
    """Stands in for a Langfuse span when tracing is off, so every caller can
    update its span unconditionally."""

    def update(self, **_):
        pass


def configure_tracing() -> None:
    """Start the Langfuse client, once, at startup. Nothing else in the app
    imports langfuse: observations are opened through observe() below."""
    global _langfuse
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        log.warning("Langfuse keys unset: calls are not traced")
        return
    from langfuse import get_client

    _langfuse = get_client()
    log.info("Langfuse tracing enabled")


def shutdown_tracing() -> None:
    """Flush pending spans. Without it the last run of a deploy is lost."""
    if _langfuse:
        _langfuse.shutdown()


def trace_attributes(**kwargs):
    """Attach attributes (metadata, tags, session_id, ...) to the whole trace
    rather than to one observation, so the traces table can be filtered by
    them. Use inside the observation that opens the trace."""
    if _langfuse is None:
        return contextlib.nullcontext()
    from langfuse import propagate_attributes

    return propagate_attributes(**kwargs)


def observe(**kwargs):
    """One Langfuse observation, nested under whatever observation is active,
    or a no-op when tracing is off. Agents use this for their own nodes and
    tool calls; every LLM call is already covered by stream() below."""
    if _langfuse is None:
        return contextlib.nullcontext(_NoSpan())
    return _langfuse.start_as_current_observation(**kwargs)


def _cost_usd(model_name: str, input_tokens: int, output_tokens: int) -> float:
    spec = MODELS[model_name]
    return (
        input_tokens / 1_000_000 * spec["input_usd_per_mtok"]
        + output_tokens / 1_000_000 * spec["output_usd_per_mtok"]
    )


async def _select(task: str) -> tuple[list[str], dict[str, str]]:
    """Split the task's model list into (usable, {skipped model: reason})."""
    candidates = ROUTING_POLICY.get(task)
    if not candidates:
        raise GatewayError("unknown_task", f"No routing policy for task type '{task}'.")
    usable, skipped = [], {}
    for name in candidates:
        spec = MODELS[name]
        if not os.getenv(spec["api_key_env"]):
            skipped[name] = NO_KEY
        elif await db.spend_today(spec["provider"]) >= DAILY_BUDGET_USD[spec["provider"]]:
            skipped[name] = OVER_BUDGET
        else:
            usable.append(name)
    return usable, skipped


def _nothing_left(skipped: dict[str, str]) -> GatewayError:
    if OVER_BUDGET in skipped.values():
        return GatewayError(
            "budget_exhausted",
            "The daily model budget for this demo is spent. Try again tomorrow.",
        )
    return GatewayError("no_provider", "No model provider is configured for this task.")


async def _log(model_name, *, task, run_id, agent_id, usage, started, fallback, success, span):
    """Record one call in both places: the generation span in Langfuse, and
    call_logs plus the budget counter in Postgres."""
    spec = MODELS[model_name]
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    span.update(
        usage_details={"input": input_tokens, "output": output_tokens},
        cost_details={"total": _cost_usd(model_name, input_tokens, output_tokens)},
        metadata={"provider": spec["provider"], "fallback_used": fallback},
    )
    await db.record_call(
        run_id=run_id,
        agent_id=agent_id,
        task_type=task,
        provider=spec["provider"],
        model=spec["litellm_model"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=_cost_usd(model_name, input_tokens, output_tokens),
        latency_ms=int((time.monotonic() - started) * 1000),
        fallback_used=fallback,
        success=success,
    )


async def stream(task: str, messages: list[dict], *, run_id: str, agent_id: str) -> AsyncIterator[dict]:
    """Yield SSE event dicts: partial_output chunks, plus fallback_triggered
    whenever a model is passed over. The caller forwards them to the client."""
    usable, skipped = await _select(task)
    if not usable:
        raise _nothing_left(skipped)

    # A model skipped for missing credentials is a deployment fact, not a
    # runtime fallback, so only budget skips and real failures are narrated.
    previous = next(
        (name for name in reversed(list(skipped)) if skipped[name] == OVER_BUDGET), None
    )
    reason = OVER_BUDGET if previous else ""

    for attempt, name in enumerate(usable):
        spec = MODELS[name]
        if previous:
            yield {
                "type": "fallback_triggered",
                "from_provider": MODELS[previous]["provider"],
                "to_provider": spec["provider"],
                "reason": reason,
            }
        started, chunks = time.monotonic(), []
        # One generation per attempt, so a fallback shows up as two siblings in
        # the trace: the model that failed and the one that answered.
        with observe(
            as_type="generation", name=name, model=spec["litellm_model"], input=messages
        ) as span:
            try:
                response = await litellm.acompletion(
                    model=spec["litellm_model"],
                    messages=messages,
                    max_tokens=MAX_TOKENS,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                async for chunk in response:
                    chunks.append(chunk)
                    text = chunk.choices[0].delta.content if chunk.choices else None
                    if text:
                        yield {"type": "partial_output", "text": text}
            except Exception as exc:  # noqa: BLE001 - mapped to a safe message below
                log.exception("provider %s failed", name)
                span.update(level="ERROR", status_message=str(exc)[:500])
                if chunks:
                    # ponytail: no mid-stream fallback - the client already has text
                    # from this provider and replaying it under another would duplicate
                    # output. Buffer the whole response before yielding if that changes.
                    raise GatewayError("provider_error", "The model stopped part way through this answer.") from exc
                previous, reason = name, "provider error"
                if attempt == len(usable) - 1:
                    raise GatewayError("provider_error", "Every model provider failed for this request.") from exc
                continue

            built = litellm.stream_chunk_builder(chunks, messages=messages)
            span.update(output=built.choices[0].message.content if built.choices else "")
            await _log(
                name, task=task, run_id=run_id, agent_id=agent_id, usage=built.usage,
                started=started, fallback=attempt > 0 or bool(previous), success=True,
                span=span,
            )
            return


async def complete(task: str, messages: list[dict], *, run_id: str, agent_id: str) -> str:
    """Non-streaming call. Same policy, same accounting, returns the text."""
    text = []
    async for event in stream(task, messages, run_id=run_id, agent_id=agent_id):
        if event["type"] == "partial_output":
            text.append(event["text"])
    return "".join(text)

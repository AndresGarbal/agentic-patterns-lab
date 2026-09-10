"""Agent registry.

An agent is an async generator that yields SSE event dicts (see
docs/03_API_CONTRACTS.md for the event types). It must end with run_complete.
Everything else in the backend only knows about this contract, so a LangGraph
graph plugs in by adding one entry to AGENT_RUNNERS.
"""
from collections.abc import AsyncIterator

from . import gateway

ECHO_SYSTEM = (
    "You are the echo agent in an AI engineering demo. Answer the user in two "
    "or three sentences, plainly, with no preamble."
)


async def run_echo(run_id: str, payload: dict) -> AsyncIterator[dict]:
    """Phase 1 smoke test: proves request -> rate limiter -> gateway -> SSE works
    end to end, across two hosts, before any agent framework is involved."""
    question = payload["question"]
    yield {"type": "node_start", "node": "echo", "label": "Echo agent"}

    parts = []
    async for event in gateway.stream(
        "echo",
        [{"role": "system", "content": ECHO_SYSTEM}, {"role": "user", "content": question}],
        run_id=run_id,
        agent_id="echo",
    ):
        if event["type"] == "partial_output":
            parts.append(event["text"])
        yield event

    yield {"type": "node_end", "node": "echo"}
    yield {"type": "run_complete", "result": {"answer_markdown": "".join(parts)}}


AGENT_RUNNERS = {
    "echo": run_echo,
    # Phase 3: "research": run_research
    # Phase 5: "financial": run_financial
}

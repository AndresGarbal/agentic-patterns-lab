"""Backend self-check. Run: python tests/test_phase1.py

No network, no database, no Redis, no API keys: the providers, the rate limiter,
and the database are stubbed so this only exercises our own logic - limits,
error shapes, SSE encoding, the agent event contract, and the gateway selection
and fallback rules.
"""
import asyncio
import contextlib
import json
import os
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, gateway, main, rate_limit  # noqa: E402


# --- API surface -----------------------------------------------------------

def test_basics(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert [a["id"] for a in client.get("/agents").json()["agents"]] == ["echo"]
    assert client.post("/agents/nope/run", json={"input": {"question": "hi"}}).status_code == 404


def test_input_validation(client):
    for payload in [{}, {"question": "   "}, {"question": "x" * 2001}]:
        r = client.post("/agents/echo/run", json={"input": payload})
        assert r.status_code == 422, r.status_code
        assert r.json()["error"] == "invalid_input"


def test_rate_limit(client, monkeypatch):
    over = rate_limit.limit_for("echo") + 1
    monkeypatch(rate_limit, "hit", lambda agent_id, ip: _async(over))
    r = client.post("/agents/echo/run", json={"input": {"question": "hi"}})
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limited" and body["agent"] == "echo"
    assert body["retry_after_seconds"] > 0


def test_echo_run_streams(client, monkeypatch):
    monkeypatch(rate_limit, "hit", lambda agent_id, ip: _async(1))

    async def fake_stream(task, messages, **kw):
        assert task == "echo"
        for word in ["Hello", " world"]:
            yield {"type": "partial_output", "text": word}

    monkeypatch(gateway, "stream", fake_stream)

    run_id = client.post("/agents/echo/run", json={"input": {"question": "hi"}}).json()["run_id"]
    events = _events(client, run_id)

    assert [e["type"] for e in events] == [
        "node_start", "partial_output", "partial_output", "node_end", "run_complete",
    ]
    assert all(e["run_id"] == run_id for e in events)
    assert events[-1]["result"]["answer_markdown"] == "Hello world"
    # A run is consumable once: a second connect must not re-run the agent.
    assert client.get(f"/agents/echo/stream/{run_id}").status_code == 404


def test_gateway_errors_are_safe(client, monkeypatch):
    monkeypatch(rate_limit, "hit", lambda agent_id, ip: _async(1))

    async def blow_up(task, messages, **kw):
        raise gateway.GatewayError("budget_exhausted", "Out of budget for today.")
        yield  # unreachable, but keeps this an async generator

    monkeypatch(gateway, "stream", blow_up)
    run_id = client.post("/agents/echo/run", json={"input": {"question": "hi"}}).json()["run_id"]
    assert _events(client, run_id)[-1] == {
        "type": "error", "message": "Out of budget for today.", "run_id": run_id,
    }


# --- Gateway selection and fallback ----------------------------------------

def test_selection_skips_unconfigured_and_broke_providers():
    async def scenario():
        with _keys(ANTHROPIC_API_KEY="x", OPENAI_API_KEY="x", GROQ_API_KEY=None):
            usable, skipped = await gateway._select("echo")
            assert usable == ["claude-haiku", "gpt-4o-mini"]
            assert skipped == {"gpt-oss-20b": gateway.NO_KEY}

            with _spend({"anthropic": 999.0}):
                usable, skipped = await gateway._select("echo")
                assert usable == ["gpt-4o-mini"]
                assert skipped["claude-haiku"] == gateway.OVER_BUDGET

            with _spend({"anthropic": 999.0, "openai": 999.0}):
                assert await _error("echo") == "budget_exhausted"

        with _keys(ANTHROPIC_API_KEY=None, OPENAI_API_KEY=None, GROQ_API_KEY=None):
            assert await _error("echo") == "no_provider"

    asyncio.run(scenario())


def test_fallback_on_provider_error():
    """The first provider fails before emitting anything, so the gateway moves to
    the next one and narrates the switch."""
    attempted = []
    logged = []

    async def acompletion(model, messages, **kw):
        attempted.append(model)
        if model.startswith("anthropic/"):
            raise RuntimeError("provider is down")
        return _chunks(["Fell ", "through"])

    async def scenario():
        with _keys(ANTHROPIC_API_KEY="x", OPENAI_API_KEY="x", GROQ_API_KEY=None):
            with _patched(gateway.litellm, acompletion=acompletion, stream_chunk_builder=_usage):
                with _patched(db, record_call=_recorder(logged)):
                    return [e async for e in gateway.stream("echo", [], run_id="r1", agent_id="echo")]

    events = asyncio.run(scenario())

    assert attempted == ["anthropic/claude-haiku-4-5", "openai/gpt-4o-mini"]
    assert events[0] == {
        "type": "fallback_triggered",
        "from_provider": "anthropic",
        "to_provider": "openai",
        "reason": "provider error",
    }
    assert "".join(e["text"] for e in events[1:]) == "Fell through"
    assert logged[0]["provider"] == "openai" and logged[0]["fallback_used"] is True
    # 11 input + 7 output tokens on gpt-4o-mini, priced from config.MODELS.
    assert abs(logged[0]["cost_usd"] - (11 * 0.15 + 7 * 0.60) / 1_000_000) < 1e-12


# --- helpers ---------------------------------------------------------------

def _async(value):
    async def run():
        return value
    return run()


def _events(client, run_id):
    body = client.get(f"/agents/echo/stream/{run_id}").text
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


async def _error(task):
    try:
        async for _ in gateway.stream(task, [], run_id="r", agent_id="echo"):
            pass
    except gateway.GatewayError as exc:
        return exc.code
    raise AssertionError("expected GatewayError")


def _chunks(texts):
    async def stream():
        for text in texts:
            delta = types.SimpleNamespace(content=text)
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])
    return stream()


def _usage(chunks, messages=None):
    usage = types.SimpleNamespace(prompt_tokens=11, completion_tokens=7)
    return types.SimpleNamespace(usage=usage)


def _recorder(sink):
    async def record_call(**call):
        sink.append(call)
    return record_call


@contextlib.contextmanager
def _keys(**env):
    original = {name: os.environ.get(name) for name in env}
    _apply(env)
    try:
        yield
    finally:
        _apply(original)


def _apply(env):
    for name, value in env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@contextlib.contextmanager
def _spend(by_provider):
    with _patched(db, spend_today=lambda provider: _async(by_provider.get(provider, 0.0))):
        yield


@contextlib.contextmanager
def _patched(target, **attrs):
    original = {name: getattr(target, name) for name in attrs}
    for name, value in attrs.items():
        setattr(target, name, value)
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(target, name, value)


def main_():
    patches = []

    def monkeypatch(module, name, value):
        patches.append((module, name, getattr(module, name)))
        setattr(module, name, value)

    with TestClient(main.app) as client:
        for fn in [test_basics, test_input_validation, test_rate_limit,
                   test_echo_run_streams, test_gateway_errors_are_safe]:
            try:
                fn(client, monkeypatch) if fn.__code__.co_argcount == 2 else fn(client)
            finally:
                for module, name, original in reversed(patches):
                    setattr(module, name, original)
                patches.clear()
            print("ok", fn.__name__)

    for fn in [test_selection_skips_unconfigured_and_broke_providers, test_fallback_on_provider_error]:
        fn()
        print("ok", fn.__name__)


if __name__ == "__main__":
    main_()

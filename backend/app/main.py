import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import db, gateway, rate_limit
from .agents import AGENT_RUNNERS
from .config import AGENTS, CORS_ORIGINS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

RUN_TTL_SECONDS = 600
# ponytail: in-process run registry. One backend instance serves this demo, so a
# dict is enough; move to Redis if the service is ever scaled past one replica.
_runs: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await rate_limit.startup()
    gateway.configure_tracing()
    yield
    await rate_limit.shutdown()
    await db.close()


app = FastAPI(title="AI Agent Lab", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    input: dict = Field(default_factory=dict)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def error(code: str, message: str, status: int, **extra) -> JSONResponse:
    return JSONResponse({"error": code, "message": message, **extra}, status_code=status)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/agents")
async def list_agents():
    return {"agents": AGENTS}


@app.get("/rate-limit/status")
async def rate_limit_status(agent_id: str, request: Request):
    return {
        "agent_id": agent_id,
        "calls_used": await rate_limit.used(agent_id, client_ip(request)),
        "calls_limit": rate_limit.limit_for(agent_id),
        "resets_at": rate_limit.resets_at().isoformat().replace("+00:00", "Z"),
    }


@app.post("/agents/{agent_id}/run", status_code=202)
async def start_run(agent_id: str, body: RunRequest, request: Request):
    if agent_id not in AGENT_RUNNERS:
        return error("unknown_agent", f"No agent named '{agent_id}'.", 404)

    question = str(body.input.get("question", "")).strip()
    if not question:
        return error("invalid_input", "Ask a question before running the agent.", 422)
    if len(question) > 2000:
        return error("invalid_input", "That question is too long (2000 characters max).", 422)

    used = await rate_limit.hit(agent_id, client_ip(request))
    if used > rate_limit.limit_for(agent_id):
        return error(
            "rate_limited",
            "Daily demo limit reached for this agent. Try again tomorrow.",
            429,
            agent=agent_id,
            retry_after_seconds=rate_limit.seconds_until_reset(),
        )

    now = time.monotonic()
    for run_id, run in list(_runs.items()):
        if now - run["created"] > RUN_TTL_SECONDS:
            del _runs[run_id]

    run_id = uuid.uuid4().hex[:12]
    _runs[run_id] = {"agent_id": agent_id, "input": {"question": question}, "created": now}
    return {"run_id": run_id}


def sse(event: dict, run_id: str) -> str:
    return f"data: {json.dumps({**event, 'run_id': run_id})}\n\n"


@app.get("/agents/{agent_id}/stream/{run_id}")
async def stream_run(agent_id: str, run_id: str):
    run = _runs.pop(run_id, None)
    if not run or run["agent_id"] != agent_id:
        return error("unknown_run", "This run has expired or was already streamed.", 404)

    async def events():
        try:
            async for event in AGENT_RUNNERS[agent_id](run_id, run["input"]):
                yield sse(event, run_id)
        except gateway.GatewayError as exc:
            yield sse({"type": "error", "message": exc.message}, run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("run %s failed", run_id)
            yield sse({"type": "error", "message": "The agent hit an unexpected error."}, run_id)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

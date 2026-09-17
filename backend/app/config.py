"""Tunable values live here, never inline in code."""
import os

# Landing page reads this over GET /agents.
AGENTS = [
    {
        "id": "echo",
        "name": "Echo agent",
        "description": "Phase 1 smoke test: one LLM call, streamed end to end.",
        "patterns": ["single call"],
    },
]

# Per agent, per IP, per UTC day.
RATE_LIMITS = {
    "echo": {"calls_per_day": 20},
    "research": {"calls_per_day": 5},
    "financial": {"calls_per_day": 5},
}

# Model catalogue. Prices are USD per million tokens, used to compute spend
# ourselves rather than trusting litellm's cost map to know every model id.
# A model whose api_key_env is unset is skipped by the gateway, so the app runs
# with any subset of providers configured.
MODELS = {
    "claude-haiku": {
        "provider": "anthropic",
        "litellm_model": "anthropic/claude-haiku-4-5",
        "api_key_env": "ANTHROPIC_API_KEY",
        "input_usd_per_mtok": 1.00,
        "output_usd_per_mtok": 5.00,
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "litellm_model": "openai/gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "input_usd_per_mtok": 0.15,
        "output_usd_per_mtok": 0.60,
    },
    # Groq's Llama models moved to enterprise-only pricing, so the two
    # self-serve gpt-oss models are what a normal key can reach.
    "gpt-oss-120b": {
        "provider": "groq",
        "litellm_model": "groq/openai/gpt-oss-120b",
        "api_key_env": "GROQ_API_KEY",
        "input_usd_per_mtok": 0.15,
        "output_usd_per_mtok": 0.60,
    },
    "gpt-oss-20b": {
        "provider": "groq",
        "litellm_model": "groq/openai/gpt-oss-20b",
        "api_key_env": "GROQ_API_KEY",
        "input_usd_per_mtok": 0.075,
        "output_usd_per_mtok": 0.30,
    },
}

# Task type -> ordered model preference. The gateway walks this list and skips
# any model that is unconfigured or whose provider is over budget, so the order
# is both a quality preference and a fallback chain.
# Every list ends in a Groq model, so with only GROQ_API_KEY set the gateway
# skips the unconfigured entries and the whole app still runs on Groq alone.
ROUTING_POLICY = {
    "echo": ["claude-haiku", "gpt-4o-mini", "gpt-oss-20b"],
    "planning": ["claude-haiku", "gpt-4o-mini", "gpt-oss-120b"],
    "structured_extract": ["gpt-4o-mini", "claude-haiku", "gpt-oss-120b"],
    # Called twice in parallel by the Financial agent, so the two entries must
    # be different models for the agreement check to mean anything.
    "verification": ["claude-haiku", "gpt-4o-mini", "gpt-oss-120b", "gpt-oss-20b"],
    "narrator": ["gpt-oss-20b", "claude-haiku"],
    "routing": ["gpt-oss-20b", "claude-haiku"],
}

DAILY_BUDGET_USD = {
    "anthropic": float(os.getenv("DAILY_BUDGET_ANTHROPIC_USD", "2.00")),
    "openai": float(os.getenv("DAILY_BUDGET_OPENAI_USD", "2.00")),
    "groq": float(os.getenv("DAILY_BUDGET_GROQ_USD", "1.00")),
}

CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))

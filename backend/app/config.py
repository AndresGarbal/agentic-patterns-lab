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
    "llama-3.1-8b": {
        "provider": "groq",
        "litellm_model": "groq/llama-3.1-8b-instant",
        "api_key_env": "GROQ_API_KEY",
        "input_usd_per_mtok": 0.05,
        "output_usd_per_mtok": 0.08,
    },
}

# Task type -> ordered model preference. The gateway walks this list and skips
# any model that is unconfigured or whose provider is over budget, so the order
# is both a quality preference and a fallback chain.
ROUTING_POLICY = {
    "echo": ["claude-haiku", "gpt-4o-mini", "llama-3.1-8b"],
    "planning": ["claude-haiku", "gpt-4o-mini"],
    "structured_extract": ["gpt-4o-mini", "claude-haiku"],
    "verification": ["claude-haiku", "gpt-4o-mini"],  # called twice in parallel by the Financial agent
    "narrator": ["llama-3.1-8b", "claude-haiku"],
    "routing": ["llama-3.1-8b", "claude-haiku"],
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

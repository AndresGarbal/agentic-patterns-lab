"""Web search tool for the Research agent. Exa today; the rest of the app
only sees the {url, title, content} dicts below, so swapping providers stays
inside this file."""
import logging
import os

import httpx

from . import gateway
from .config import WEB_SEARCH

log = logging.getLogger(__name__)
_URL = "https://api.exa.ai/search"


class WebSearchError(Exception):
    """Carries a short code and a message that is safe to show in the UI."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def web_search(query: str) -> list[dict]:
    """One {url, title, content} dict per page found, with content capped at
    WEB_SEARCH["max_chars_per_page"]. Pages Exa could not read are dropped.
    Full page text rather than Exa's highlights, because chunking and
    retrieval happen on our side: that is the RAG this agent demonstrates."""
    key = os.getenv("EXA_API_KEY")
    if not key:
        raise WebSearchError("web_search_unavailable",
                             "Web search is not configured on this server.")
    with gateway.observe(as_type="tool", name="web_search", input={"query": query}) as span:
        try:
            async with httpx.AsyncClient(timeout=WEB_SEARCH["timeout_s"]) as client:
                response = await client.post(
                    _URL,
                    headers={"x-api-key": key},
                    json={
                        "query": query,
                        "numResults": WEB_SEARCH["num_results"],
                        "contents": {"text": {"maxCharacters": WEB_SEARCH["max_chars_per_page"]}},
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            log.exception("web search failed")
            span.update(level="ERROR", status_message=str(exc)[:500])
            raise WebSearchError(
                "web_search_failed", "The web search failed for this request.") from exc
        data = response.json()
        results = [{
            "url": item["url"], 
            "title": item.get("title") or item["url"], 
            "content": item["text"]}
                   for item in data["results"] 
                   if item.get("text")]
        span.update(output={"count": len(results)},
                    metadata={"cost_usd": data.get("costDollars", {}).get("total")})
    return results

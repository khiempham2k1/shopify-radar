"""Exa web search through its free hosted MCP server (no API key), as Agent Reach does."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from radar.collectors.base import CollectError
from radar.settings import get_settings


@dataclass
class SearchHit:
    title: str
    url: str
    text: str = ""
    published: str = ""
    author: str = ""


def parse_exa_text(text: str) -> list[SearchHit]:
    """Exa MCP has returned both JSON and a 'Title:/URL:/Text:' plain format; accept either."""
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            results = data.get("results", data) if isinstance(data, dict) else data
            hits = []
            for r in results if isinstance(results, list) else []:
                if isinstance(r, dict) and r.get("url"):
                    hits.append(
                        SearchHit(
                            title=str(r.get("title") or r["url"]),
                            url=str(r["url"]),
                            text=str(r.get("text") or r.get("summary") or ""),
                            published=str(r.get("publishedDate") or ""),
                            author=str(r.get("author") or ""),
                        )
                    )
            return hits
    hits: list[SearchHit] = []
    for block in re.split(r"\n(?=Title:)", "\n" + text):
        title = re.search(r"^Title:\s*(.*)$", block, re.M)
        url = re.search(r"^URL:\s*(\S+)", block, re.M)
        if not url:
            continue
        published = re.search(r"^Published(?: Date)?:\s*(.*)$", block, re.M)
        author = re.search(r"^Author:\s*(.*)$", block, re.M)
        body = re.search(r"^(?:Text|Highlights|Summary):\s*(.*)", block, re.M | re.S)
        hits.append(
            SearchHit(
                title=(title.group(1).strip() if title else url.group(1)),
                url=url.group(1).strip(),
                text=(body.group(1).strip() if body else ""),
                published=(published.group(1).strip() if published else ""),
                author=(author.group(1).strip() if author else ""),
            )
        )
    return hits


async def _call(url: str, tool: str, arguments: dict[str, Any], timeout: float) -> str:
    from mcp import Client

    async with Client(url, read_timeout_seconds=timeout) as client:
        result = await client.call_tool(tool, arguments)
    if getattr(result, "isError", False) or getattr(result, "is_error", False):
        raise CollectError(f"Exa báo lỗi: {result}")
    return "\n".join(getattr(block, "text", "") for block in getattr(result, "content", []) or [])


def exa_search(query: str, num_results: int = 8, timeout: float = 60.0) -> list[SearchHit]:
    url = get_settings().exa_mcp_url
    try:
        text = asyncio.run(_call(url, "web_search_exa", {"query": query, "numResults": num_results}, timeout))
    except CollectError:
        raise
    except Exception as exc:  # noqa: BLE001 - network/protocol errors surface on the health page
        raise CollectError(f"Exa MCP lỗi: {exc.__class__.__name__}: {exc}") from exc
    return parse_exa_text(text)

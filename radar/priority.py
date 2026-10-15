"""Priority topics from config/priorities.txt.

One topic per line. The first term is the topic name and is also searched on
every source that takes queries (Reddit, X, YouTube, web search, Hacker News).
Other ways of writing it follow after `|`; a term wrapped in slashes is a
regular expression:

    Shopify Canvas | Canvas editor | /canvas\\s+(app|api|block)s?/

Items that mention a topic are always shown, get a score boost and are listed
first on the overview page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PriorityTopic:
    name: str
    patterns: list[re.Pattern[str]] = field(default_factory=list)

    @property
    def query(self) -> str:
        return self.name

    def matches(self, text: str) -> bool:
        return any(p.search(text) for p in self.patterns)


def _pattern(term: str) -> re.Pattern[str]:
    if len(term) > 2 and term.startswith("/") and term.endswith("/"):
        return re.compile(term[1:-1], re.IGNORECASE)
    # Whole words only, so "Canvas" does not match "canvassing".
    return re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, term.split())) + r"(?!\w)", re.IGNORECASE)


def parse_priorities(text: str) -> list[PriorityTopic]:
    topics: list[PriorityTopic] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        terms = [t.strip() for t in line.split("|") if t.strip()]
        if not terms or terms[0].startswith("/"):
            raise ValueError(f"Dòng {number}: tên chủ đề phải là chữ thường, không phải /regex/")
        try:
            patterns = [_pattern(t) for t in terms]
        except re.error as exc:
            raise ValueError(f"Dòng {number}: regex sai ({exc})") from exc
        topics.append(PriorityTopic(name=terms[0][:80], patterns=patterns))
    return topics


def match_priorities(topics: list[PriorityTopic], text: str) -> list[str]:
    return [t.name for t in topics if t.matches(text)]


def priority_value(topics: list[PriorityTopic], text: str) -> str | None:
    """Comma-joined topic names for the items.priority column, or None."""
    names = match_priorities(topics, text)
    return ", ".join(names)[:300] if names else None

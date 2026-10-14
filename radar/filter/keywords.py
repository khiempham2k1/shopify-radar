"""Keyword filter using TrendRadar's frequency_words syntax.

File layout::

    [GLOBAL_FILTER]          # titles containing any of these are dropped everywhere
    hiring
    /\\bfor sale\\b/

    [WORD_GROUPS]            # optional marker; a blank line separates groups
    [Checkout]               # first-line [alias] names the group
    checkout extensibility   # plain word: OR within the group
    /checkout\\.liquid/       # /regex/ (case-insensitive)
    thank you page => Trang cảm ơn   # display alias for one word
    +shopify                 # required: every + word must match
    !job                     # exclude: drop the item for this group only
    @20                      # show at most 20 items for this group

Lines starting with ``#`` are comments. Matching is case-insensitive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

RESERVED_SECTIONS = {"GLOBAL_FILTER", "WORD_GROUPS"}


@dataclass
class Word:
    raw: str
    pattern: re.Pattern[str] | None = None
    alias: str = ""

    def matches(self, text: str) -> bool:
        if self.pattern is not None:
            return bool(self.pattern.search(text))
        return self.raw.lower() in text

    @property
    def display(self) -> str:
        return self.alias or self.raw


@dataclass
class WordGroup:
    alias: str = ""
    normal: list[Word] = field(default_factory=list)
    required: list[Word] = field(default_factory=list)
    excluded: list[Word] = field(default_factory=list)
    limit: int = 0

    @property
    def name(self) -> str:
        if self.alias:
            return self.alias
        shown = [w.display for w in self.normal] or [w.display for w in self.required]
        return " / ".join(dict.fromkeys(shown))

    def matches(self, text: str) -> bool:
        if any(w.matches(text) for w in self.excluded):
            return False
        if self.required and not all(w.matches(text) for w in self.required):
            return False
        if self.normal:
            return any(w.matches(text) for w in self.normal)
        return bool(self.required)


@dataclass
class KeywordConfig:
    global_filter: list[Word] = field(default_factory=list)
    groups: list[WordGroup] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.groups

    def is_blocked(self, text: str) -> bool:
        lowered = text.lower()
        return any(w.matches(lowered) for w in self.global_filter)

    def match(self, text: str) -> list[str]:
        """Names of the groups this text matches. Empty if blocked or nothing matches."""
        lowered = text.lower()
        if self.is_blocked(lowered):
            return []
        return [g.name for g in self.groups if g.matches(lowered)]

    def limits(self) -> dict[str, int]:
        return {g.name: g.limit for g in self.groups if g.limit}


def _parse_word(token: str) -> Word:
    alias = ""
    if "=>" in token:
        token, alias = (part.strip() for part in token.split("=>", 1))
    regex = re.fullmatch(r"/(.+)/([a-z]*)", token)
    if regex:
        # Patterns are always case-insensitive; trailing flags are accepted for
        # compatibility with TrendRadar files (e.g. /\bAI\b/i).
        try:
            return Word(raw=token, pattern=re.compile(regex.group(1), re.IGNORECASE), alias=alias)
        except re.error as exc:
            raise ValueError(f"Regex không hợp lệ trong keywords: {token} ({exc})") from exc
    return Word(raw=token, alias=alias)


def parse_keywords(text: str) -> KeywordConfig:
    config = KeywordConfig()
    section = "WORD_GROUPS"
    current: WordGroup | None = None

    def close_group() -> None:
        nonlocal current
        if current and (current.normal or current.required):
            config.groups.append(current)
        current = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            continue
        if not line:
            close_group()
            continue

        bracket = re.fullmatch(r"\[(.+)\]", line)
        if bracket and bracket.group(1).strip() in RESERVED_SECTIONS:
            close_group()
            section = bracket.group(1).strip()
            continue

        if section == "GLOBAL_FILTER" and bracket:
            # A group alias ends the global filter even without a [WORD_GROUPS] marker.
            section = "WORD_GROUPS"

        if section == "GLOBAL_FILTER":
            config.global_filter.append(_parse_word(line))
            continue

        if bracket:
            close_group()
            current = WordGroup(alias=bracket.group(1).strip())
            continue

        if current is None:
            current = WordGroup()
        if re.fullmatch(r"@\d+", line):
            current.limit = int(line[1:])
        elif line.startswith("+") and len(line) > 1:
            current.required.append(_parse_word(line[1:].strip()))
        elif line.startswith("!") and len(line) > 1:
            current.excluded.append(_parse_word(line[1:].strip()))
        else:
            current.normal.append(_parse_word(line))

    close_group()
    return config

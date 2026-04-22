from __future__ import annotations

from datetime import datetime
from pathlib import Path


def file_id(path: Path) -> str:
    """Node id is the filename stem. decision-graphql-api.md → decision-graphql-api"""
    return path.stem


def format_timestamp(ts: datetime) -> str:
    """Compact display format. Always in the object's tz (UTC for mtime-derived)."""
    return ts.strftime("%Y-%m-%d %H:%M")


def match_files(files: list[Path], query: str) -> list[Path]:
    """Match a query against filename stems.

    Preference order:
      1. exact stem match (case-insensitive)
      2. stem starts with query
      3. stem contains query as substring
    Stops at the first non-empty tier — so a perfect match never gets mixed
    with fuzzy ones.
    """
    q = query.lower()
    exact = [f for f in files if f.stem.lower() == q]
    if exact:
        return exact
    prefix = [f for f in files if f.stem.lower().startswith(q)]
    if prefix:
        return prefix
    return [f for f in files if q in f.stem.lower()]


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def type_from_path(path: Path) -> str:
    """Derive the knowledge-type label from the parent directory name.

    data/knowledge/decisions/foo.md → "decision"
    data/knowledge/meetings/x.md    → "meeting"
    """
    parent = path.parent.name
    return parent[:-1] if parent.endswith("s") else parent

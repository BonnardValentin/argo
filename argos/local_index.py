from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from argos.reader import ParsedNode, parse_file


@dataclass
class IndexEntry:
    id: str
    title: str
    timestamp: datetime
    path: Path
    preview: str


def list_nodes(data_dir: Path) -> list[Path]:
    """Return all .md files under data_dir (walks type subdirs), sorted."""
    if not data_dir.exists():
        return []
    return sorted(data_dir.rglob("*.md"))


def load_index(data_dir: Path) -> list[IndexEntry]:
    """Load all nodes as IndexEntry. Unreadable files are skipped silently."""
    entries: list[IndexEntry] = []
    for path in list_nodes(data_dir):
        try:
            node = parse_file(path)
        except (OSError, UnicodeDecodeError):
            continue
        entries.append(_to_entry(path, node))
    return entries


def recent(data_dir: Path, n: int) -> list[IndexEntry]:
    """Top-N most recent nodes, newest first."""
    entries = load_index(data_dir)
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries[:n]


def _to_entry(path: Path, node: ParsedNode) -> IndexEntry:
    timestamp = node.timestamp or _file_mtime(path)
    decision = node.sections.get("Decision", "")
    preview = _first_lines(decision, n=2)
    return IndexEntry(
        id=node.id,
        title=node.title,
        timestamp=timestamp,
        path=path,
        preview=preview,
    )


def _file_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _first_lines(text: str, n: int) -> str:
    non_blank = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(non_blank[:n])

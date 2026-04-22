from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ParsedNode:
    id: str
    title: str
    sections: dict[str, str] = field(default_factory=dict)
    timestamp: datetime | None = None
    raw: str = ""


def parse_file(path: Path) -> ParsedNode:
    """Parse a knowledge-node markdown file.

    Handles two shapes:
      - Plain: `# Title` + `## Section` blocks.
      - Frontmatter: leading `---\\n<yaml>\\n---\\n` followed by the plain body.

    Only the `timestamp:` key in the frontmatter is parsed — the rest is
    discarded. Everything else comes from the body.
    """
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    title = _extract_title(body) or path.stem
    sections = _split_sections(body)
    timestamp = _extract_timestamp(frontmatter) if frontmatter else None

    return ParsedNode(
        id=path.stem,
        title=title,
        sections=sections,
        timestamp=timestamp,
        raw=text,
    )


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter_text, body_text). Frontmatter is None if absent."""
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            frontmatter = "".join(lines[1:i])
            body = "".join(lines[i + 1 :]).lstrip("\n")
            return frontmatter, body
    return None, text  # no closing delimiter — treat as no frontmatter


def _extract_title(body: str) -> str | None:
    """First `# Title` line, or None if the body doesn't lead with one."""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
        # first non-blank line isn't an H1 — no title
        return None
    return None


def _split_sections(body: str) -> dict[str, str]:
    """Split body into {H2 header: content}. Preserves section order in dict."""
    sections: dict[str, str] = {}
    current_name: str | None = None
    current_buf: list[str] = []

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_name is not None:
                sections[current_name] = "\n".join(current_buf).strip()
            current_name = stripped[3:].strip()
            current_buf = []
        elif current_name is not None:
            current_buf.append(line)

    if current_name is not None:
        sections[current_name] = "\n".join(current_buf).strip()
    return sections


def _extract_timestamp(frontmatter: str) -> datetime | None:
    """Pull the `timestamp:` line from frontmatter without a full YAML parser.

    Accepts quoted or unquoted ISO-8601 values. Returns None on anything weird.
    """
    for line in frontmatter.splitlines():
        if not line.startswith("timestamp:"):
            continue
        value = line.split(":", 1)[1].strip()
        value = value.strip("'\"")
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None

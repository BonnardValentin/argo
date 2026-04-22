"""Ingest documentation from a local repository tree.

Walks a root directory matching a set of well-known documentation patterns
(README, ARCHITECTURE, CONTRIBUTING, CHANGELOG, CLAUDE.md / AGENTS.md,
docs/**, adrs/**, decisions/**) and yields `RawArtifact` values. Pure I/O —
no LLM, no network. The same deterministic contract as the GitHub ingester.

The extractor downstream decides if a file carries decision/discussion
signal or is noise. README-style files that are pure reference material
will be dropped via the `keep=false` path.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path

from argos.models import RawArtifact, Source


# Patterns are glob-matched against paths relative to the repo root.
# Order is informational; dedup happens via a `seen` set in iter_docs.
DEFAULT_PATTERNS: tuple[str, ...] = (
    # Top-level conventions
    "README.md",
    "README.rst",
    "README.txt",
    "ARCHITECTURE.md",
    "ARCH.md",
    "DESIGN.md",
    "DOCS.md",
    "NOTES.md",
    "ROADMAP.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "GOVERNANCE.md",
    # AI / agent instruction files
    "CLAUDE.md",
    "AGENT.md",
    "AGENTS.md",
    ".cursorrules",
    # ADR / decision records
    "*.adr.md",
    "adr/**/*.md",
    "adrs/**/*.md",
    "decisions/**/*.md",
    "architecture/**/*.md",
    # Generic docs directories
    "docs/**/*.md",
    "doc/**/*.md",
    # Monorepo conventions — top-level convention files at any depth
    "**/README.md",
    "**/ARCHITECTURE.md",
    "**/DESIGN.md",
    "**/CLAUDE.md",
    "**/AGENTS.md",
    "**/AGENT.md",
)


# Always-skipped subtrees.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git/*",
    ".git/**",
    "node_modules/*",
    "node_modules/**",
    ".venv/*",
    ".venv/**",
    "venv/*",
    "venv/**",
    "env/*",
    "env/**",
    "dist/*",
    "dist/**",
    "build/*",
    "build/**",
    "target/*",
    "target/**",
    "__pycache__/*",
    "__pycache__/**",
    ".pytest_cache/*",
    ".pytest_cache/**",
    "*.egg-info/*",
    "*.egg-info/**",
)


class LocalDocsIngestor:
    """Walk a directory for documentation artifacts.

    Deterministic: same filesystem state in → same RawArtifacts out.
    Large files (> `max_bytes`) are truncated with a flag in extras so the
    extractor at least sees the beginning (where TL;DR / decisions usually
    live). Tiny files (< `min_bytes`) are dropped — these are almost always
    placeholder README stubs.
    """

    def __init__(
        self,
        root: Path,
        *,
        patterns: tuple[str, ...] = DEFAULT_PATTERNS,
        excludes: tuple[str, ...] = DEFAULT_EXCLUDES,
        min_bytes: int = 80,
        max_bytes: int = 200_000,
    ) -> None:
        self.root = root.resolve()
        self.patterns = patterns
        self.excludes = excludes
        self.min_bytes = min_bytes
        self.max_bytes = max_bytes

    def iter_docs(self, *, max_items: int | None = None) -> Iterator[RawArtifact]:
        seen: set[Path] = set()
        count = 0
        for pattern in self.patterns:
            for path in sorted(self.root.glob(pattern)):
                if not path.is_file():
                    continue
                try:
                    rel = path.relative_to(self.root)
                except ValueError:
                    continue
                if rel in seen:
                    continue
                if self._excluded(rel):
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size < self.min_bytes:
                    continue
                seen.add(rel)
                artifact = self._read_artifact(path, rel, size)
                if artifact is None:
                    continue
                yield artifact
                count += 1
                if max_items and count >= max_items:
                    return

    def _excluded(self, rel: Path) -> bool:
        s = rel.as_posix()
        for pat in self.excludes:
            if fnmatch(s, pat):
                return True
            # Also guard against the pattern matching a parent directory.
            if any(fnmatch(part, pat.rstrip("/**").rstrip("/*")) for part in rel.parts):
                return True
        return False

    def _read_artifact(
        self, path: Path, rel: Path, size: int
    ) -> RawArtifact | None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        truncated = False
        if size > self.max_bytes:
            text = text[: self.max_bytes]
            truncated = True

        title = _first_h1(text) or path.name

        try:
            created_at = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            )
        except OSError:
            created_at = None

        return RawArtifact(
            source=Source(
                kind="local",
                url=None,
                ref=rel.as_posix(),
                fetched_at=datetime.now(timezone.utc),
            ),
            title=title,
            body=text,
            author=None,
            created_at=created_at,
            extras={
                "path": str(path),
                "size": size,
                "truncated": truncated,
                "repo_root": str(self.root),
            },
        )


def _first_h1(text: str) -> str | None:
    """Return the first `# Header` line after any YAML frontmatter."""
    in_frontmatter = False
    frontmatter_closed = False
    for i, raw_line in enumerate(text.splitlines()):
        line = raw_line.strip()
        # YAML frontmatter handling: opens and closes with a bare `---`
        if i == 0 and line == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line == "---":
                in_frontmatter = False
                frontmatter_closed = True
            continue
        if not line:
            continue
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
        # First non-blank, non-H1 line → give up (title must lead).
        if frontmatter_closed or i > 0:
            return None
    return None

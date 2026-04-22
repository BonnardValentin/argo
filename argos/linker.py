"""Hermes Linker — the first graph layer over Argos.

Consumes (new_node, candidates) — where candidates are the top-K results from
vector similarity — and emits a small, high-precision set of typed directed
edges. Never touches nodes, embeddings, or Redis. Edges live in JSON on disk.

Two classifier backends share one Protocol:
- `LLMClassifier`  — batches all K candidates into one Anthropic call, low
                     latency per source and strong type inference.
- `HeuristicClassifier` — no-network fallback; cosine-only; emits `related_to`
                     exclusively because directional relations (depends_on,
                     caused_by, …) cannot be inferred from similarity alone.

`get_linker()` selects LLM when ANTHROPIC_API_KEY is set, heuristic otherwise.

Confidence math
---------------
LLM mode: conf = 0.6 × llm_self_confidence + 0.4 × cosine_similarity
Heuristic mode: conf = cosine_similarity
Both components are clamped to [0, 1] before blending. Edges below
`min_confidence` (default 0.6, per spec) are logged and dropped.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from anthropic import Anthropic

from argos.reader import parse_file
from argos.utils import type_from_path

logger = logging.getLogger("argos.linker")

# Allow-list from the spec; anything else is rejected even if a classifier emits it.
ALLOWED_RELATIONS: set[str] = {
    "depends_on",
    "contradicts",
    "refines",
    "caused_by",
    "related_to",
}

MIN_CONFIDENCE: float = 0.6
DEFAULT_TOP_K: int = 5


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class Edge:
    source_id: str
    target_id: str
    type: str
    confidence: float
    reason: str

    def key(self) -> tuple[str, str, str]:
        return (self.source_id, self.target_id, self.type)


@dataclass
class NodeSnapshot:
    """A flattened view of a knowledge node — what we show a classifier."""

    id: str
    type: str
    title: str
    context: str = ""
    decision: str = ""
    why: str = ""
    how: str = ""

    @classmethod
    def load(cls, path: Path) -> "NodeSnapshot":
        parsed = parse_file(path)
        return cls(
            id=path.stem,
            type=type_from_path(path),
            title=parsed.title,
            context=parsed.sections.get("Context", ""),
            decision=parsed.sections.get("Decision", ""),
            why=parsed.sections.get("Why", ""),
            how=parsed.sections.get("How", ""),
        )

    def content_for_search(self) -> str:
        """Canonical text used when retrieving similar candidates. Mirrors
        `argos.indexer._node_content` so the linker sees the same doc shape
        the index was built from."""
        parts = [self.title]
        for label, value in (
            ("Context", self.context),
            ("Decision", self.decision),
            ("Why", self.why),
            ("How", self.how),
        ):
            if value.strip():
                parts.append(f"{label}: {value}")
        return "\n\n".join(parts)

    def render_for_prompt(self) -> str:
        lines = [f"id: {self.id}", f"type: {self.type}", f"title: {self.title}"]
        for label, value in (
            ("Context", self.context),
            ("Decision", self.decision),
            ("Why", self.why),
            ("How", self.how),
        ):
            if value.strip():
                lines.append(f"\n{label}:\n{value.strip()}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Classifiers
# ---------------------------------------------------------------------------


@runtime_checkable
class RelationClassifier(Protocol):
    name: str

    def classify_batch(
        self,
        source: NodeSnapshot,
        candidates: list[tuple[NodeSnapshot, float]],
    ) -> list[Edge | None]: ...


class HeuristicClassifier:
    """No-LLM fallback. Cosine-only → `related_to` edges."""

    def __init__(self, threshold: float = 0.75) -> None:
        self.threshold = threshold
        self.name = f"heuristic(cosine>={threshold})"

    def classify_batch(
        self,
        source: NodeSnapshot,
        candidates: list[tuple[NodeSnapshot, float]],
    ) -> list[Edge | None]:
        out: list[Edge | None] = []
        for cand, similarity in candidates:
            if similarity < self.threshold:
                out.append(None)
                continue
            out.append(
                Edge(
                    source_id=source.id,
                    target_id=cand.id,
                    type="related_to",
                    confidence=round(max(0.0, min(1.0, similarity)), 3),
                    reason=f"cosine={similarity:.2f}",
                )
            )
        return out


LLM_SYSTEM_PROMPT = """You are Hermes, the relationship classifier for a knowledge graph.

You are shown ONE source node and a list of CANDIDATE nodes retrieved by vector
similarity. For each candidate, decide whether the source has a meaningful
DIRECTED relationship to it (source → candidate).

Allowed relation types:
  - depends_on : source relies on / assumes / extends the candidate
  - contradicts : source and candidate reach incompatible conclusions on the same topic
  - refines : source updates, supersedes, or narrows the candidate (newer thinking on the same topic)
  - caused_by : source exists BECAUSE of the candidate (e.g. decision caused by an incident)
  - related_to : same topic cluster, but no stronger relation fits
  - skip : no meaningful relationship — just shared vocabulary, or too weak to assert

Rules:
- Prefer SKIP. Sparsity beats density.
- Shared keywords alone are NOT a relationship.
- If unsure between two relation types, pick the weaker one. If still unsure, skip.
- Confidence is 0.0-1.0 and reflects how sure you are in the TYPE. Do not inflate.
- Every candidate must be classified exactly once, keyed by candidate_id.

Output: one call to `classify_edges`."""


CLASSIFY_TOOL = {
    "name": "classify_edges",
    "description": "Classify each candidate against the source node.",
    "input_schema": {
        "type": "object",
        "properties": {
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": [
                                "depends_on",
                                "contradicts",
                                "refines",
                                "caused_by",
                                "related_to",
                                "skip",
                            ],
                        },
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["candidate_id", "type"],
                },
            },
        },
        "required": ["edges"],
    },
}


class LLMClassifier:
    """Claude-backed classifier. One batched tool-use call per source node."""

    def __init__(
        self, *, api_key: str, model: str = "claude-haiku-4-5-20251001"
    ) -> None:
        self._client = Anthropic(api_key=api_key)
        self._model = model
        self.name = f"anthropic:{model}"

    def classify_batch(
        self,
        source: NodeSnapshot,
        candidates: list[tuple[NodeSnapshot, float]],
    ) -> list[Edge | None]:
        if not candidates:
            return []

        prompt = self._render_prompt(source, candidates)
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            temperature=0,
            system=LLM_SYSTEM_PROMPT,
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "classify_edges"},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_use = next(
            (b for b in resp.content if getattr(b, "type", None) == "tool_use"),
            None,
        )
        if tool_use is None:
            logger.warning("llm returned no tool_use for source=%s", source.id)
            return [None] * len(candidates)

        by_id: dict[str, dict] = {}
        for entry in tool_use.input.get("edges", []) or []:
            cid = entry.get("candidate_id")
            if cid:
                by_id[cid] = entry

        out: list[Edge | None] = []
        for cand, similarity in candidates:
            entry = by_id.get(cand.id)
            if not entry:
                out.append(None)
                continue
            rel_type = entry.get("type")
            if rel_type in (None, "skip") or rel_type not in ALLOWED_RELATIONS:
                out.append(None)
                continue
            try:
                llm_conf = float(entry.get("confidence", 0.0))
            except (TypeError, ValueError):
                llm_conf = 0.0
            llm_conf = max(0.0, min(1.0, llm_conf))
            sim_clamped = max(0.0, min(1.0, similarity))
            # 60/40 blend: LLM type confidence anchored by retrieval similarity.
            blended = 0.6 * llm_conf + 0.4 * sim_clamped
            out.append(
                Edge(
                    source_id=source.id,
                    target_id=cand.id,
                    type=rel_type,
                    confidence=round(blended, 3),
                    reason=(entry.get("reason") or "")[:300],
                )
            )
        return out

    @staticmethod
    def _render_prompt(
        source: NodeSnapshot, candidates: list[tuple[NodeSnapshot, float]]
    ) -> str:
        parts = ["--- SOURCE ---", source.render_for_prompt(), "", "--- CANDIDATES ---"]
        for i, (cand, sim) in enumerate(candidates, 1):
            parts.append(f"\n[{i}] similarity={sim:.3f}")
            parts.append(cand.render_for_prompt())
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Linker:
    def __init__(
        self,
        classifier: RelationClassifier,
        *,
        min_confidence: float = MIN_CONFIDENCE,
        exclude_self: bool = True,
    ) -> None:
        self.classifier = classifier
        self.min_confidence = min_confidence
        self.exclude_self = exclude_self

    def link(
        self,
        new_node: NodeSnapshot,
        candidates: list[tuple[NodeSnapshot, float]],
    ) -> list[Edge]:
        """Classify candidates, validate, dedup, return surviving edges."""
        filtered: list[tuple[NodeSnapshot, float]] = []
        for cand, sim in candidates:
            if self.exclude_self and cand.id == new_node.id:
                logger.debug("skip self-match: %s", cand.id)
                continue
            filtered.append((cand, sim))

        logger.debug(
            "linking source=%s against %d candidate(s) via %s",
            new_node.id, len(filtered), self.classifier.name,
        )

        classifications = self.classifier.classify_batch(new_node, filtered)

        edges: list[Edge] = []
        seen: set[tuple[str, str, str]] = set()
        for (cand, sim), edge in zip(filtered, classifications):
            if edge is None:
                logger.debug("no relation: %s → %s (sim=%.3f)", new_node.id, cand.id, sim)
                continue
            if edge.type not in ALLOWED_RELATIONS:
                logger.debug("reject bad type %r for %s → %s",
                             edge.type, edge.source_id, edge.target_id)
                continue
            if edge.confidence < self.min_confidence:
                logger.debug(
                    "reject low-confidence %.2f: %s → %s [%s]",
                    edge.confidence, edge.source_id, edge.target_id, edge.type,
                )
                continue
            k = edge.key()
            if k in seen:
                continue
            seen.add(k)
            edges.append(edge)
            logger.info(
                "edge: %s → %s [%s] conf=%.2f — %s",
                edge.source_id, edge.target_id, edge.type,
                edge.confidence, edge.reason,
            )
        return edges


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class EdgeStore:
    """JSON-backed graph store. Keyed on (source_id, target_id, type).

    `upsert` merges new edges with existing ones in-place: repeated `kb index`
    runs converge to a stable set instead of growing unbounded.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[Edge]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("malformed %s — starting fresh", self.path)
            return []
        edges: list[Edge] = []
        for item in raw:
            try:
                edges.append(
                    Edge(
                        source_id=item["source_id"],
                        target_id=item["target_id"],
                        type=item["type"],
                        confidence=float(item.get("confidence", 0.0)),
                        reason=item.get("reason", ""),
                    )
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("dropping malformed edge: %r", item)
        return edges

    def save(self, edges: list[Edge]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sorted_edges = sorted(edges, key=lambda e: e.key())
        payload = [asdict(e) for e in sorted_edges]
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def upsert(self, new_edges: list[Edge]) -> tuple[int, int]:
        """Merge new_edges in. Returns (added, updated)."""
        existing = self.load()
        by_key: dict[tuple[str, str, str], Edge] = {e.key(): e for e in existing}
        added = 0
        updated = 0
        for edge in new_edges:
            k = edge.key()
            if k in by_key:
                prev = by_key[k]
                if (prev.confidence, prev.reason) != (edge.confidence, edge.reason):
                    updated += 1
            else:
                added += 1
            by_key[k] = edge
        self.save(list(by_key.values()))
        return added, updated


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_linker(
    *,
    api_key: str | None = None,
    model: str | None = None,
    min_confidence: float | None = None,
    heuristic_threshold: float | None = None,
) -> Linker:
    """Resolve a Linker from env. LLM backend if ANTHROPIC_API_KEY is set,
    otherwise the heuristic fallback."""
    api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or None
    min_conf = (
        min_confidence
        if min_confidence is not None
        else float(os.getenv("ARGOS_LINKER_MIN_CONFIDENCE", str(MIN_CONFIDENCE)))
    )

    classifier: RelationClassifier
    if api_key:
        classifier = LLMClassifier(
            api_key=api_key,
            model=model or os.getenv("ARGOS_LINKER_MODEL") or "claude-haiku-4-5-20251001",
        )
    else:
        threshold = (
            heuristic_threshold
            if heuristic_threshold is not None
            else float(os.getenv("ARGOS_LINKER_HEURISTIC_THRESHOLD", "0.75"))
        )
        logger.info("no ANTHROPIC_API_KEY — using heuristic linker (threshold=%.2f)", threshold)
        classifier = HeuristicClassifier(threshold=threshold)

    return Linker(classifier, min_confidence=min_conf)

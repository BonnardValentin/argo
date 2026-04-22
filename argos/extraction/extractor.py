from __future__ import annotations

import json
from datetime import datetime, timezone

from anthropic import Anthropic
from slugify import slugify

from argos.models import KnowledgeNode, KnowledgeType, RawArtifact

SYSTEM_PROMPT = """You are the extraction stage of a knowledge graph pipeline.

Your job: look at one raw artifact (a PR, issue, Slack thread, or commit) and
decide if it carries genuine engineering signal worth preserving — a decision,
a non-trivial discussion, an incident, or a lasting note.

Hard filter: most artifacts are NOISE. Typo fixes, dependency bumps, cosmetic
refactors, rubber-stamp approvals, "LGTM" threads — all noise. When in doubt,
drop it. Precision over recall.

When signal IS present, extract structured fields:
- title: short, declarative, ≤ 80 chars
- context: what situation prompted this? (1–3 sentences)
- decision: what was chosen / concluded? (empty string if type != decision)
- why: the reasoning, including constraints that forced the choice
- how: the implementation approach or mechanism (empty if not applicable)
- tradeoffs: what was given up; each a short phrase
- alternatives: other options considered; each a short phrase
- open_questions: unresolved items flagged in the discussion
- type: one of decision | discussion | incident | note

Rules:
- Every field must be grounded in the artifact. Do NOT invent.
- Use the artifact's own terminology where possible.
- Empty list / empty string is valid — do not pad.
- Decide type by dominant intent, not surface form. A PR can be a "decision".

Call the `emit` tool exactly once: either with keep=true and the fields
populated, or keep=false with a one-line reason."""


EMIT_TOOL = {
    "name": "emit",
    "description": "Emit the extraction result. Use keep=false to drop the artifact.",
    "input_schema": {
        "type": "object",
        "properties": {
            "keep": {"type": "boolean"},
            "reason": {
                "type": "string",
                "description": "When keep=false, 1 line on why this is noise.",
            },
            "type": {"type": "string", "enum": [t.value for t in KnowledgeType]},
            "title": {"type": "string"},
            "context": {"type": "string"},
            "decision": {"type": "string"},
            "why": {"type": "string"},
            "how": {"type": "string"},
            "tradeoffs": {"type": "array", "items": {"type": "string"}},
            "alternatives": {"type": "array", "items": {"type": "string"}},
            "open_questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["keep"],
    },
}


class Extractor:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = Anthropic(api_key=api_key)
        self._model = model

    def extract(self, artifact: RawArtifact) -> KnowledgeNode | None:
        """Returns a KnowledgeNode or None if the artifact carries no signal."""
        user_content = _render_artifact(artifact)

        resp = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            temperature=0,
            system=SYSTEM_PROMPT,
            tools=[EMIT_TOOL],
            tool_choice={"type": "tool", "name": "emit"},
            messages=[{"role": "user", "content": user_content}],
        )

        tool_use = next(
            (b for b in resp.content if getattr(b, "type", None) == "tool_use"), None
        )
        if tool_use is None:
            return None

        data = tool_use.input
        if not data.get("keep"):
            return None

        timestamp = artifact.created_at or datetime.now(timezone.utc)
        node_id = _make_id(artifact, data.get("title", ""))

        return KnowledgeNode(
            id=node_id,
            type=KnowledgeType(data.get("type", "note")),
            title=data.get("title", artifact.title)[:200],
            context=data.get("context", ""),
            decision=data.get("decision", ""),
            why=data.get("why", ""),
            how=data.get("how", ""),
            tradeoffs=data.get("tradeoffs", []) or [],
            alternatives=data.get("alternatives", []) or [],
            open_questions=data.get("open_questions", []) or [],
            timestamp=timestamp,
            sources=[artifact.source],
        )


def _render_artifact(artifact: RawArtifact) -> str:
    """Flatten the artifact into a single user message. Deterministic output
    so the extractor's input is stable across runs."""
    lines = [
        f"Source: {artifact.source.kind} ({artifact.source.ref or artifact.source.url})",
        f"Author: {artifact.author or 'unknown'}",
        f"Created: {artifact.created_at.isoformat() if artifact.created_at else 'unknown'}",
        f"Title: {artifact.title}",
        "",
        "--- Body ---",
        artifact.body or "(empty)",
    ]
    extras = artifact.extras or {}
    comments = extras.get("comments") or []
    if comments:
        lines.append("")
        lines.append("--- Comments ---")
        for c in comments:
            lines.append(f"[{c.get('author', 'unknown')}] {c.get('body', '')}")
    other = {k: v for k, v in extras.items() if k != "comments"}
    if other:
        lines.append("")
        lines.append("--- Metadata ---")
        lines.append(json.dumps(other, default=str, indent=2))
    return "\n".join(lines)


def _make_id(artifact: RawArtifact, title: str) -> str:
    """Stable, human-readable ID derived from source ref + title."""
    ref = artifact.source.ref or artifact.fingerprint()
    slug = slugify(title or artifact.title or "untitled")[:60] or "untitled"
    ref_slug = slugify(ref)[:40]
    return f"{ref_slug}--{slug}"

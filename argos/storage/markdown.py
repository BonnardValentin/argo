from __future__ import annotations

from pathlib import Path

import frontmatter

from argos.models import KnowledgeNode, RelationType, Relationship, Source


def node_path(data_dir: Path, node: KnowledgeNode) -> Path:
    """Nest by pluralized type: data_dir/decisions/decision-<id>.md."""
    return data_dir / f"{node.type.value}s" / f"{node.type.value}-{node.id}.md"


def write_node(data_dir: Path, node: KnowledgeNode) -> Path:
    """Write a node to markdown. Idempotent: same id → same file, overwritten."""
    path = node_path(data_dir, node)
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(
        content=_render_body(node),
        **_render_metadata(node),
    )
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return path


def read_node(path: Path) -> KnowledgeNode:
    post = frontmatter.load(path)
    meta = post.metadata
    return KnowledgeNode(
        id=meta["id"],
        type=meta["type"],
        title=meta["title"],
        context=meta.get("context", ""),
        decision=meta.get("decision", ""),
        why=meta.get("why", ""),
        how=meta.get("how", ""),
        tradeoffs=meta.get("tradeoffs", []) or [],
        alternatives=meta.get("alternatives", []) or [],
        open_questions=meta.get("open_questions", []) or [],
        timestamp=meta["timestamp"],
        sources=[Source(**s) for s in meta.get("sources", [])],
        relations=[
            Relationship(type=RelationType(r["type"]), target_id=r["target_id"], rationale=r.get("rationale"))
            for r in meta.get("relations", [])
        ],
    )


def _render_metadata(node: KnowledgeNode) -> dict:
    return {
        "id": node.id,
        "type": node.type.value,
        "title": node.title,
        "timestamp": node.timestamp.isoformat(),
        "sources": [
            {
                "kind": s.kind,
                "url": s.url,
                "ref": s.ref,
                "fetched_at": s.fetched_at.isoformat(),
            }
            for s in node.sources
        ],
        "relations": [
            {"type": r.type.value, "target_id": r.target_id, "rationale": r.rationale}
            for r in node.relations
        ],
    }


def _render_body(node: KnowledgeNode) -> str:
    parts: list[str] = [f"# {node.title}", ""]

    def section(header: str, content: str) -> None:
        if content.strip():
            parts.extend([f"## {header}", "", content.strip(), ""])

    def bullets(header: str, items: list[str]) -> None:
        if items:
            parts.extend([f"## {header}", ""])
            parts.extend(f"- {item}" for item in items)
            parts.append("")

    section("Context", node.context)
    section("Decision", node.decision)
    section("Why", node.why)
    section("How", node.how)
    bullets("Tradeoffs", node.tradeoffs)
    bullets("Alternatives", node.alternatives)
    bullets("Open questions", node.open_questions)

    if node.sources:
        parts.extend(["## Sources", ""])
        for s in node.sources:
            label = s.ref or s.url or s.kind
            parts.append(f"- [{label}]({s.url})" if s.url else f"- {label}")
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"

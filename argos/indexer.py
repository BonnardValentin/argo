"""Redis-backed vector index.

Walks markdown files under data_dir, embeds a compact representation of each
node, and writes the result into Redis hashes keyed `argos:node:<id>`. A
RediSearch FT index over those hashes enables KNN queries from search.py.

Markdown is the source of truth. Everything here is a derived artifact —
`kb index --reset` drops and rebuilds freely.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import redis
from redis.commands.search.field import NumericField, TagField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.exceptions import ResponseError

from argos.embedding import Embedder, get_embedder, pack_floats
from argos.local_index import list_nodes
from argos.reader import ParsedNode, parse_file
from argos.utils import type_from_path

NODE_KEY_PREFIX = "argos:node:"


def node_key(node_id: str) -> str:
    return f"{NODE_KEY_PREFIX}{node_id}"


@dataclass
class RedisIndex:
    client: redis.Redis
    index_name: str
    embedder: Embedder

    def ensure_index(self) -> bool:
        """Create the FT index if missing. Returns True if we created it."""
        try:
            self.client.ft(self.index_name).info()
            return False
        except ResponseError as exc:
            if "Unknown" not in str(exc) and "no such index" not in str(exc).lower():
                raise

        schema = (
            TagField("id"),
            TagField("type"),
            TextField("title"),
            TextField("content"),
            NumericField("timestamp", sortable=True),
            VectorField(
                "embedding",
                "FLAT",
                {
                    "TYPE": "FLOAT32",
                    "DIM": self.embedder.dim,
                    "DISTANCE_METRIC": "COSINE",
                },
            ),
        )
        definition = IndexDefinition(
            prefix=[NODE_KEY_PREFIX], index_type=IndexType.HASH
        )
        self.client.ft(self.index_name).create_index(schema, definition=definition)
        return True

    def drop_index(self, *, delete_documents: bool = True) -> None:
        """Drop the index (and by default, all documents it owns)."""
        try:
            self.client.ft(self.index_name).dropindex(
                delete_documents=delete_documents
            )
        except ResponseError:
            pass  # already absent

    def index_path(self, path: Path) -> str:
        node = parse_file(path)
        content = _node_content(node)
        vec = self.embedder.embed(content)
        key = node_key(node.id)
        ts = (
            int(node.timestamp.timestamp())
            if node.timestamp
            else int(path.stat().st_mtime)
        )
        self.client.hset(
            key,
            mapping={
                "id": node.id,
                "type": type_from_path(path),
                "title": node.title,
                "content": content,
                "timestamp": ts,
                "path": str(path),
                "embedding": pack_floats(vec),
            },
        )
        return key

    def index_dir(self, data_dir: Path) -> int:
        self.ensure_index()
        count = 0
        for path in list_nodes(data_dir):
            self.index_path(path)
            count += 1
        return count


@dataclass
class BuildResult:
    indexed: int
    embedder: Embedder
    linker_name: str | None = None
    edges_added: int = 0
    edges_updated: int = 0
    edges_total: int = 0


def build(
    data_dir: Path,
    *,
    redis_url: str,
    index_name: str,
    reset: bool = False,
    embedder: Embedder | None = None,
    linker: "Linker | None" = None,
    edge_store: "EdgeStore | None" = None,
    link_top_k: int = 5,
) -> BuildResult:
    """Build or refresh the Redis index from markdown; optionally link.

    Phase 1 — embed every node and write to Redis.
    Phase 2 (if `linker` and `edge_store` are provided) — for each node,
    retrieve top-K similar via FT.SEARCH, classify, upsert edges.
    """
    embedder = embedder or get_embedder()
    client = redis.Redis.from_url(redis_url)
    idx = RedisIndex(client=client, index_name=index_name, embedder=embedder)
    if reset:
        idx.drop_index()
    count = idx.index_dir(data_dir)
    result = BuildResult(indexed=count, embedder=embedder)

    if linker is not None and edge_store is not None and count > 0:
        _run_linking(
            result=result,
            data_dir=data_dir,
            redis_url=redis_url,
            index_name=index_name,
            embedder=embedder,
            linker=linker,
            edge_store=edge_store,
            top_k=link_top_k,
        )
    return result


def _run_linking(
    *,
    result: BuildResult,
    data_dir: Path,
    redis_url: str,
    index_name: str,
    embedder: Embedder,
    linker: "Linker",
    edge_store: "EdgeStore",
    top_k: int,
) -> None:
    # Local imports to keep indexer.py usable when the linker module is absent
    # (e.g. during minimal test setups).
    from argos.linker import NodeSnapshot
    from argos.search import search as vector_search

    all_new_edges = []
    for path in list_nodes(data_dir):
        source = NodeSnapshot.load(path)
        # Ask for k+1 so we can drop the self-match.
        hits = vector_search(
            source.content_for_search(),
            redis_url=redis_url,
            index_name=index_name,
            k=top_k + 1,
            embedder=embedder,
        )
        pairs: list[tuple[NodeSnapshot, float]] = []
        for hit in hits:
            if hit.id == source.id:
                continue
            if not hit.path.exists():
                continue
            pairs.append((NodeSnapshot.load(hit.path), hit.score))
            if len(pairs) >= top_k:
                break
        edges = linker.link(source, pairs)
        all_new_edges.extend(edges)

    added, updated = edge_store.upsert(all_new_edges)
    result.linker_name = linker.classifier.name
    result.edges_added = added
    result.edges_updated = updated
    result.edges_total = len(edge_store.load())


def _node_content(node: ParsedNode) -> str:
    """Build the text we actually embed. Title + decision-relevant sections."""
    parts: list[str] = [node.title]
    for section in ("Context", "Decision", "Why", "How"):
        value = node.sections.get(section, "").strip()
        if value:
            parts.append(f"{section}: {value}")
    return "\n\n".join(parts)



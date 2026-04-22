"""KNN search over the Redis vector index.

Embeds the query with the same backend used at index time (see embedding.py),
then asks RediSearch for the top-K nearest documents via FT.SEARCH.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import redis
from redis.commands.search.query import Query

from argos.embedding import Embedder, get_embedder, pack_floats
from argos.indexer import NODE_KEY_PREFIX


@dataclass
class SearchResult:
    id: str
    type: str
    title: str
    path: Path
    score: float  # cosine similarity, in [-1, 1] — higher is better


def search(
    query: str,
    *,
    redis_url: str,
    index_name: str,
    k: int = 5,
    embedder: Embedder | None = None,
) -> list[SearchResult]:
    embedder = embedder or get_embedder()
    client = redis.Redis.from_url(redis_url)
    vec = embedder.embed(query)

    q = (
        Query(f"*=>[KNN {k} @embedding $vec AS distance]")
        .sort_by("distance")
        .return_fields("type", "title", "path", "distance")
        .paging(0, k)
        .dialect(2)
    )
    response = client.ft(index_name).search(
        q, query_params={"vec": pack_floats(vec)}
    )

    results: list[SearchResult] = []
    for doc in response.docs:
        key = _decode(doc.id)  # Document.id is the Redis key
        node_id = (
            key[len(NODE_KEY_PREFIX):] if key.startswith(NODE_KEY_PREFIX) else key
        )
        distance = float(_decode(doc.distance))
        results.append(
            SearchResult(
                id=node_id,
                type=_decode(getattr(doc, "type", "")),
                title=_decode(getattr(doc, "title", "")),
                path=Path(_decode(getattr(doc, "path", ""))),
                score=1.0 - distance,
            )
        )
    return results


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if value is not None else ""

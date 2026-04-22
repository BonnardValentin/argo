"""Embedder abstraction + two implementations.

The rest of the system talks to `Embedder` (a Protocol). A real OpenAI-compatible
endpoint is used when an API key is configured; otherwise we fall back to a
deterministic hash embedder so the pipeline runs end-to-end without network
access. Replace / extend by adding another class and wiring it into
`get_embedder()`.
"""

from __future__ import annotations

import hashlib
import math
import os
import random
import re
import struct
from typing import Protocol, runtime_checkable

import httpx


@runtime_checkable
class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic bag-of-hashed-tokens embedder.

    For each alnum token we derive a unit-normalized Gaussian vector seeded by
    sha256(token). We sum and L2-normalize the result. Shared tokens → similar
    vectors. Not semantic, but good enough to exercise the pipeline.
    """

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.name = f"hash-bag-v1:{dim}"

    def embed(self, text: str) -> list[float]:
        tokens = _tokenize(text)
        if not tokens:
            return [0.0] * self.dim
        acc = [0.0] * self.dim
        for tok in tokens:
            tv = _token_vector(tok, self.dim)
            for i, v in enumerate(tv):
                acc[i] += v
        norm = math.sqrt(sum(v * v for v in acc)) or 1.0
        return [v / norm for v in acc]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class OpenAIEmbedder:
    """Calls an OpenAI-compatible /embeddings endpoint via httpx.

    Works with OpenAI directly, or any compatible gateway (Ollama, vLLM, etc.)
    by overriding ARGOS_EMBEDDING_BASE_URL.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "text-embedding-3-small",
        dim: int = 1536,
    ) -> None:
        self.model = model
        self.dim = dim
        self.name = f"openai:{model}:{dim}"
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload: dict = {
            "model": self.model,
            "input": texts,
            "encoding_format": "float",
        }
        if self._supports_dim():
            payload["dimensions"] = self.dim
        resp = self._client.post("/embeddings", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return [row["embedding"] for row in data["data"]]

    def close(self) -> None:
        self._client.close()

    def _supports_dim(self) -> bool:
        # Only the v3 family of OpenAI models accepts `dimensions`.
        return "text-embedding-3" in self.model


def get_embedder() -> Embedder:
    """Resolve an embedder from env. Falls back to HashEmbedder when no API
    key is configured — keeps `kb index` / `kb ask` working offline."""
    provider = (os.getenv("ARGOS_EMBEDDING_PROVIDER") or "").lower() or None
    api_key = os.getenv("ARGOS_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("ARGOS_EMBEDDING_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("ARGOS_EMBEDDING_MODEL", "text-embedding-3-small")
    dim_env = os.getenv("ARGOS_EMBEDDING_DIM")

    if provider == "hash" or (provider is None and not api_key):
        return HashEmbedder(dim=int(dim_env) if dim_env else 384)

    if not api_key:
        raise RuntimeError(
            "openai embedding selected but no API key set "
            "(ARGOS_EMBEDDING_API_KEY or OPENAI_API_KEY)"
        )
    return OpenAIEmbedder(
        api_key=api_key,
        base_url=base_url,
        model=model,
        dim=int(dim_env) if dim_env else 1536,
    )


def pack_floats(vec: list[float]) -> bytes:
    """Pack a vector as little-endian float32, as RediSearch expects."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _token_vector(token: str, dim: int) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    return [rng.gauss(0.0, 1.0) for _ in range(dim)]

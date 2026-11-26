"""Dense + sparse embeddings for hybrid search.

- "fastembed": a multilingual dense model (Arabic + English) and BM25 sparse vectors,
  both run locally on CPU. Models download on first use.
- "hash": dependency-free character n-gram hashing. Not semantic, but deterministic and
  offline, so tests and a no-network demo still work end to end.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from functools import lru_cache

from app.config import settings

HASH_DIM = 384
_TOKEN = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)


class Embedder:
    name: str
    dim: int
    # Cosine similarity that counts as a "fully relevant" match for this model. Raw cosine
    # ranges differ a lot between models, so the gate uses cosine / full_relevance (capped at 1).
    full_relevance: float = 0.6

    def dense(self, texts: list[str]) -> list[list[float]]: ...
    def sparse(self, texts: list[str], query: bool = False) -> list[tuple[list[int], list[float]]]: ...


def _h(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")


class HashEmbedder(Embedder):
    name = "hash"
    dim = HASH_DIM
    full_relevance = 0.3

    def dense(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            s = f"  {t.lower()}  "
            for i in range(len(s) - 2):
                h = _h(s[i : i + 3])
                v[h % self.dim] += 1.0 if (h >> 20) & 1 else -1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out

    def sparse(self, texts: list[str], query: bool = False) -> list[tuple[list[int], list[float]]]:
        out = []
        for t in texts:
            counts: dict[int, float] = {}
            for tok in _TOKEN.findall(t.lower()):
                idx = _h(tok) % (2**31 - 1)
                counts[idx] = counts.get(idx, 0.0) + 1.0
            out.append((list(counts.keys()), list(counts.values())))
        return out


class FastEmbedder(Embedder):
    name = "fastembed"
    full_relevance = float(os.getenv("RELEVANCE_FULL", "0.6"))

    def __init__(self) -> None:
        from fastembed import SparseTextEmbedding, TextEmbedding

        self._dense = TextEmbedding(settings.dense_model)
        # Stemming is English-only; disable it so Arabic tokens are kept intact.
        self._sparse = SparseTextEmbedding("Qdrant/bm25", disable_stemmer=True)
        self.dim = len(next(iter(self._dense.embed(["probe"]))))

    def dense(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._dense.embed(texts)]

    def sparse(self, texts: list[str], query: bool = False) -> list[tuple[list[int], list[float]]]:
        gen = self._sparse.query_embed(texts) if query else self._sparse.embed(texts)
        return [(e.indices.tolist(), e.values.tolist()) for e in gen]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    return HashEmbedder() if settings.embeddings == "hash" else FastEmbedder()

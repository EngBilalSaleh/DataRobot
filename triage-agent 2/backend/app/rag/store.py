"""Qdrant-backed hybrid retrieval over two collections.

- kb:        knowledge-base articles and policies
- resolved:  previously resolved tickets; the issue is embedded, the resolution is returned

Search fuses dense (semantic) and sparse (BM25 keyword) results with reciprocal rank fusion.
Keyword matching matters for product codes and for Arabic, where small embedding models
are weaker.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from qdrant_client import QdrantClient, models

from app.config import settings
from app.models import Chunk
from app.rag.embed import get_embedder

COLLECTIONS = ("kb", "resolved")
_NS = uuid.UUID("6f1c5b1e-3c7a-4f3e-9a51-0d6f2b7c9e10")


@lru_cache(maxsize=1)
def client() -> QdrantClient:
    if settings.qdrant_url:
        return QdrantClient(url=settings.qdrant_url)
    return QdrantClient(path=settings.qdrant_path)


def _collection_name(source: str) -> str:
    return f"{source}_{get_embedder().name}"


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_NS, chunk_id))


def recreate(source: str) -> None:
    c = client()
    name = _collection_name(source)
    if c.collection_exists(name):
        c.delete_collection(name)
    c.create_collection(
        name,
        vectors_config={"dense": models.VectorParams(size=get_embedder().dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )


def upsert(source: str, items: list[dict]) -> int:
    """items: dicts with id, title, text (returned to the agent), embed_text, lang, plus any metadata."""
    emb = get_embedder()
    embed_texts = [i.get("embed_text") or f"{i['title']}\n{i['text']}" for i in items]
    dense = emb.dense(embed_texts)
    sparse = emb.sparse(embed_texts)
    points = [
        models.PointStruct(
            id=point_id(item["id"]),
            vector={"dense": d, "sparse": models.SparseVector(indices=s[0], values=s[1])},
            payload={k: v for k, v in item.items() if k != "embed_text"} | {"source": source},
        )
        for item, d, s in zip(items, dense, sparse)
    ]
    client().upsert(_collection_name(source), points=points)
    return len(points)


def is_ready() -> bool:
    c = client()
    return all(c.collection_exists(_collection_name(s)) for s in COLLECTIONS)


def _lang_filter(lang: str | None) -> models.Filter | None:
    if not lang:
        return None
    return models.Filter(must=[models.FieldCondition(key="lang", match=models.MatchValue(value=lang))])


def search(query: str, source: str, lang: str | None = None, k: int = 4) -> list[Chunk]:
    """Hybrid search; prefers the customer's language and falls back to any language."""
    emb = get_embedder()
    dense = emb.dense([query])[0]
    idx, vals = emb.sparse([query], query=True)[0]
    sparse = models.SparseVector(indices=idx, values=vals)

    for flt in (_lang_filter(lang), None):
        res = client().query_points(
            _collection_name(source),
            prefetch=[
                models.Prefetch(query=dense, using="dense", limit=20, filter=flt),
                models.Prefetch(query=sparse, using="sparse", limit=20, filter=flt),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k,
            with_payload=True,
        ).points
        if res:
            return [
                Chunk(
                    id=p.payload["id"],
                    title=p.payload["title"],
                    text=p.payload["text"],
                    lang=p.payload["lang"],
                    source=source,  # type: ignore[arg-type]
                    score=round(p.score, 4),
                )
                for p in res
            ]
    return []


def relevance(query: str, source: str = "kb", lang: str | None = None) -> float:
    """How well the knowledge covers this ticket, 0 to 1: the best dense cosine match,
    scaled by what counts as a strong match for the embedding model in use."""
    emb = get_embedder()
    dense = emb.dense([query])[0]
    for flt in (_lang_filter(lang), None):
        res = client().query_points(
            _collection_name(source), query=dense, using="dense", limit=1, query_filter=flt
        ).points
        if res:
            return round(min(1.0, max(0.0, float(res[0].score)) / emb.full_relevance), 3)
    return 0.0


def get_chunk(chunk_id: str) -> Chunk | None:
    for source in COLLECTIONS:
        name = _collection_name(source)
        if not client().collection_exists(name):
            continue
        hits = client().retrieve(name, ids=[point_id(chunk_id)], with_payload=True)
        if hits:
            p = hits[0].payload
            return Chunk(id=p["id"], title=p["title"], text=p["text"], lang=p["lang"], source=source)  # type: ignore[arg-type]
    return None

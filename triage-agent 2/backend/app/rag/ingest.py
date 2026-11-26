"""Load the knowledge base and resolved tickets into Qdrant.

    python -m app.rag.ingest
"""

from __future__ import annotations

import yaml

from app.config import settings
from app.rag import store

MAX_CHARS = 700


def _chunks(article: dict) -> list[dict]:
    """Group paragraphs into chunks of at most ~MAX_CHARS, each prefixed with the title."""
    paragraphs = [p.strip() for p in article["body"].split("\n") if p.strip()]
    groups: list[list[str]] = [[]]
    for p in paragraphs:
        if groups[-1] and sum(len(x) for x in groups[-1]) + len(p) > MAX_CHARS:
            groups.append([])
        groups[-1].append(p)
    return [
        {
            "id": f"{article['id']}#{i}",
            "article_id": article["id"],
            "title": article["title"],
            "text": "\n".join(g),
            "lang": article["lang"],
            "product": article.get("product", "general"),
            "intent": article.get("intent", "other"),
        }
        for i, g in enumerate(groups, start=1)
    ]


def load_kb() -> list[dict]:
    with open(settings.data_dir / "kb.yaml", encoding="utf-8") as f:
        articles = yaml.safe_load(f)
    return [c for a in articles for c in _chunks(a)]


def load_resolved() -> list[dict]:
    with open(settings.data_dir / "resolved_tickets.yaml", encoding="utf-8") as f:
        rows = yaml.safe_load(f)
    return [
        {
            "id": r["id"],
            "title": f"Resolved ticket {r['id']}",
            "text": f"Issue: {r['issue']}\nResolution: {r['resolution']}",
            "embed_text": r["issue"],
            "lang": r["lang"],
        }
        for r in rows
    ]


def ingest() -> dict[str, int]:
    counts = {}
    for source, items in (("kb", load_kb()), ("resolved", load_resolved())):
        store.recreate(source)
        counts[source] = store.upsert(source, items)
    return counts


def ensure_ingested() -> None:
    if not store.is_ready():
        ingest()


if __name__ == "__main__":
    print(f"Embeddings: {settings.embeddings}")
    for source, n in ingest().items():
        print(f"  {source}: {n} chunks")

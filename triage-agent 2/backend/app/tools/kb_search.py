"""A CrewAI tool so the resolve agent can run follow-up searches beyond the context the
Flow already retrieved. Every result carries its chunk ID, which the agent must cite."""

from __future__ import annotations

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from app.rag import store


class KBSearchInput(BaseModel):
    query: str = Field(description="What to look up, in English or Arabic")
    language: str = Field(default="", description="'en' or 'ar' to prefer that language; empty for any")


class KBSearchTool(BaseTool):
    name: str = "knowledge_base_search"
    description: str = (
        "Search Sahab Telecom's knowledge base and previously resolved tickets. "
        "Returns passages with their IDs. Cite the IDs you rely on."
    )
    args_schema: type[BaseModel] = KBSearchInput

    def _run(self, query: str, language: str = "") -> str:
        hits = store.search(query, "kb", language or None, k=3) + store.search(query, "resolved", language or None, k=2)
        if not hits:
            return "No matching passages."
        return "\n\n".join(f"[{h.id}] {h.title}\n{h.text}" for h in hits)

"""One place to choose models. All LLM calls go to Groq's OpenAI-compatible endpoint.

CrewAI's native OpenAI client is pointed at Groq's base URL, so no extra SDK or LiteLLM is
needed. The "openai/" prefix selects that client; what follows is the Groq model ID, which for
the gpt-oss models itself starts with "openai/" (e.g. "openai/gpt-oss-120b").

A small, fast model classifies; a stronger one drafts. Cost and latency follow the value of
the step.
"""

from __future__ import annotations

from typing import Literal

from crewai import LLM

from app.config import settings

Role = Literal["classify", "draft", "insights"]


def get_llm(role: Role) -> LLM:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to .env, or set OFFLINE_MODE=true to run without an LLM.")
    model = {
        "classify": settings.classify_model,
        "draft": settings.draft_model,
        "insights": settings.insights_model,
    }[role]
    return LLM(
        model=f"openai/{model}",
        base_url=settings.groq_base_url,
        api_key=settings.groq_api_key,
        temperature=0.0 if role == "classify" else 0.2,
    )

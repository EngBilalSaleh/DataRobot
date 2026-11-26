"""Typed contracts shared by the flow, the crews, the API and the evaluation.

Every crew returns one of these models (output_pydantic), so no step ever parses free text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["billing", "technical", "account", "fraud", "complaint", "other"]
Urgency = Literal["low", "medium", "high", "critical"]
Sentiment = Literal["positive", "neutral", "negative", "angry"]
Lang = Literal["en", "ar"]


class Classification(BaseModel):
    intent: Intent
    product: str = Field(description="One of: mobile_postpaid, mobile_prepaid, home_fiber, wallet, general")
    urgency: Urgency
    sentiment: Sentiment
    confidence: float = Field(ge=0, le=1, description="How sure you are of intent and urgency, 0 to 1")
    risk_flags: list[Literal["fraud", "legal", "vip", "regulator", "safety"]] = Field(default_factory=list)
    summary: str = Field(description="One sentence, in English, of what the customer needs")


class Draft(BaseModel):
    reply: str = Field(description="The reply to the customer, in the customer's language")
    citations: list[str] = Field(description="IDs of the knowledge chunks the reply relies on")
    language: Lang


class Route(BaseModel):
    queue: str
    priority: Literal["P1", "P2", "P3", "P4"]
    sla_hours: int
    rule: str = Field(description="Which routing rule matched, for the audit trail")


class StaffingMove(BaseModel):
    from_queue: str
    to_queue: str
    agents: int = Field(ge=1)
    reason: str


class StaffingSuggestion(BaseModel):
    summary: str
    moves: list[StaffingMove] = Field(default_factory=list)


class Chunk(BaseModel):
    id: str
    title: str
    text: str
    lang: str
    source: Literal["kb", "resolved"]
    score: float = 0.0


class TraceEvent(BaseModel):
    step: str
    status: Literal["started", "done", "info"]
    detail: str = ""
    data: dict = Field(default_factory=dict)
    at: str = ""


Status = Literal["new", "triaging", "auto_sent", "pending_review", "resolved", "rejected", "failed"]


class TicketState(BaseModel):
    """The single source of truth that moves through the Flow. @persist saves it after each step."""

    id: str = ""  # flow state id, required by @persist
    ticket_id: int = 0
    subject: str = ""
    raw_text: str = ""
    redacted: str = ""
    redactions: dict[str, int] = Field(default_factory=dict)
    language: str = ""
    classification: Classification | None = None
    context: list[Chunk] = Field(default_factory=list)
    top_relevance: float = 0.0
    draft: Draft | None = None
    route: Route | None = None
    gate_score: float = 0.0
    gate_reasons: list[str] = Field(default_factory=list)
    decision: Literal["auto", "review", ""] = ""
    status: Status = "new"
    final_reply: str = ""
    trace: list[TraceEvent] = Field(default_factory=list)

    # Filled only by the review flow
    review_action: Literal["approve", "reject", ""] = ""
    human_reply: str = ""
    queue_override: str = ""
    reviewer: str = ""

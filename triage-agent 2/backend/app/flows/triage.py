"""The triage Flow: the backbone of the agent.

    ingest -> classify -> retrieve -> draft -> route -> gate --auto--> auto_send
                                                           \\-review-> hold_for_review

Agentic where it adds judgment (classify, draft), deterministic where it must be exact
(redaction, retrieval, routing, the gate). @persist saves the typed state after every
step, so a ticket held for review can be resumed later by ReviewFlow.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from crewai.flow import Flow, listen, persist, router, start

from app import offline
from app.config import settings
from app.events import broker
from app.models import Classification, Draft, TicketState, TraceEvent
from app.rag import store
from app.structured import kickoff_structured
from app.routing import gate as gate_decision
from app.routing import route as route_by_rules
from app.text import detect_language, redact


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class _Emitting:
    """Mixin: record a step in the state's trace and publish it to the ticket's live stream."""

    state: TicketState

    def emit(self, step: str, status: str, detail: str = "", data: dict | None = None) -> None:
        event = TraceEvent(step=step, status=status, detail=detail, data=data or {}, at=_now())  # type: ignore[arg-type]
        self.state.trace.append(event)
        broker.publish(self.state.ticket_id, event.model_dump())


@persist()
class TriageFlow(_Emitting, Flow[TicketState]):
    @start()
    def ingest(self) -> None:
        self.emit("ingest", "started", "Redacting personal data and detecting language")
        self.state.status = "triaging"
        self.state.redacted, self.state.redactions = redact(self.state.raw_text)
        self.state.language = detect_language(self.state.raw_text)
        self.emit(
            "ingest",
            "done",
            f"Language: {self.state.language}. Redacted: "
            + (", ".join(f"{n} {k.lower().replace('_', ' ')}" for k, n in self.state.redactions.items()) or "nothing"),
            {"language": self.state.language, "redactions": self.state.redactions, "redacted": self.state.redacted},
        )

    @listen(ingest)
    def classify(self) -> None:
        self.emit("classify", "started", "Classify crew is labeling the ticket")
        if settings.offline:
            c = offline.classify(self.state.redacted, self.state.subject)
        else:
            from app.crews.classify.crew import ClassifyCrew

            c, _ = kickoff_structured(
                ClassifyCrew().crew(),
                {"subject": self.state.subject, "text": self.state.redacted, "language": self.state.language},
                Classification,
            )
        self.state.classification = c
        self.emit(
            "classify",
            "done",
            f"{c.intent} / {c.urgency} / {c.sentiment}, confidence {c.confidence:.2f}",
            c.model_dump(),
        )

    @listen(classify)
    def retrieve(self) -> None:
        self.emit("retrieve", "started", "Hybrid search over the knowledge base and resolved tickets")
        query = self.state.redacted
        if self.state.classification:
            query = f"{self.state.classification.summary}\n{query}"
        lang = self.state.language or None
        kb = store.search(query, "kb", lang, k=4)
        resolved = store.search(query, "resolved", lang, k=2)
        self.state.context = kb + resolved
        self.state.top_relevance = store.relevance(self.state.redacted, "kb", lang)
        self.emit(
            "retrieve",
            "done",
            f"{len(kb)} articles, {len(resolved)} resolved tickets; relevance {self.state.top_relevance:.2f}",
            {"chunks": [{"id": ch.id, "title": ch.title, "source": ch.source, "score": ch.score} for ch in self.state.context]},
        )

    @listen(retrieve)
    def draft(self) -> None:
        self.emit("draft", "started", "Resolve crew is drafting a cited reply")
        c = self.state.classification
        assert c is not None
        if settings.offline:
            d = offline.draft(c, self.state.context, self.state.language)
        else:
            from app.crews.resolve.crew import ResolveCrew

            context = "\n\n".join(f"[{ch.id}] {ch.title}\n{ch.text}" for ch in self.state.context)
            crew_def = ResolveCrew()
            crew_def.allowed_ids = {ch.id for ch in self.state.context}
            d, recovered = kickoff_structured(
                crew_def.crew(),
                {
                    "text": self.state.redacted,
                    "language": self.state.language,
                    "classification": json.dumps(c.model_dump(), ensure_ascii=False),
                    "context": context or "(no passages found)",
                },
                Draft,
            )
            # Only cite what was actually retrieved. A recovered answer skipped the guardrail,
            # so this check matters most then; an empty list sends the ticket to review.
            valid = [x for x in d.citations if x in crew_def.allowed_ids]
            if valid != d.citations:
                d = d.model_copy(update={"citations": valid})
            if recovered:
                self.emit("draft", "info", "Recovered the draft from a rejected tool call and validated it")
        self.state.draft = d
        self.emit("draft", "done", f"{len(d.reply.split())} words, cites {', '.join(d.citations) or 'nothing'}", d.model_dump())

    @listen(draft)
    def route(self) -> None:
        c = self.state.classification
        assert c is not None
        self.state.route = route_by_rules(c)
        r = self.state.route
        self.emit("route", "done", f"{r.queue}, {r.priority}, SLA {r.sla_hours}h (rule: {r.rule})", r.model_dump())

    @router(route)
    def gate(self) -> str:
        c = self.state.classification
        assert c is not None
        score, decision, reasons = gate_decision(c, self.state.draft, self.state.top_relevance)
        self.state.gate_score, self.state.decision, self.state.gate_reasons = score, decision, reasons  # type: ignore[assignment]
        self.emit(
            "gate",
            "done",
            f"{'Auto-send' if decision == 'auto' else 'Human review'}: {'; '.join(reasons)}",
            {"score": score, "decision": decision, "reasons": reasons, "threshold": settings.gate_threshold},
        )
        return decision

    @listen("auto")
    def auto_send(self) -> None:
        assert self.state.draft is not None
        self.state.final_reply = self.state.draft.reply
        self.state.status = "auto_sent"
        self.emit("send", "done", "Reply sent to the customer; ticket logged in the queue for QA sampling")

    @listen("review")
    def hold_for_review(self) -> None:
        self.state.status = "pending_review"
        q = self.state.route.queue if self.state.route else "General"
        self.emit("hold", "done", f"Held in {q} with the draft attached, waiting for a human agent")


@persist()
class ReviewFlow(_Emitting, Flow[TicketState]):
    """Resumes a held ticket. Kicked off with restore_from_state_id = the triage flow's id, so it
    starts from the exact persisted state, plus the human's decision as inputs."""

    @start()
    def apply_review(self) -> None:
        s = self.state
        if s.queue_override and s.route and s.queue_override != s.route.queue:
            old = s.route.queue
            s.route = s.route.model_copy(update={"queue": s.queue_override, "rule": f"human override (was {old})"})
            self.emit("review", "info", f"{s.reviewer or 'Reviewer'} moved the ticket from {old} to {s.queue_override}")

        if s.review_action == "reject":
            s.status = "rejected"
            s.final_reply = ""
            self.emit("review", "done", f"{s.reviewer or 'Reviewer'} rejected the draft; the agent will write the reply")
            return

        edited = bool(s.human_reply and s.draft and s.human_reply.strip() != s.draft.reply.strip())
        s.final_reply = s.human_reply.strip() if s.human_reply else (s.draft.reply if s.draft else "")
        s.status = "resolved"
        self.emit(
            "review",
            "done",
            f"{s.reviewer or 'Reviewer'} {'edited and approved' if edited else 'approved'} the reply; sent to the customer",
            {"edited": edited},
        )

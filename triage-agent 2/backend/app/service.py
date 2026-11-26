"""Application services: create tickets, run the flows, record results, seed data, insights."""

from __future__ import annotations

import json
import logging
import random
import traceback
from datetime import timedelta

import yaml
from sqlmodel import select

from app import offline
from app.config import settings
from app.db import AuditLog, Ticket, audit, session, utcnow
from app.events import broker
from app.flows.triage import ReviewFlow, TriageFlow
from app.models import StaffingSuggestion, TicketState
from app.routing import queues

log = logging.getLogger("triage")


# ---------------------------------------------------------------- tickets and flows

def create_ticket(subject: str, body: str, customer: str = "Customer", channel: str = "email") -> Ticket:
    with session() as s:
        t = Ticket(subject=subject, body=body, customer=customer, channel=channel)
        s.add(t)
        s.commit()
        s.refresh(t)
        audit(s, t.id, "system", "created", json.dumps({"channel": channel}))
        s.commit()
        return t


def _save_state(ticket_id: int, state: TicketState, **extra: str) -> None:
    with session() as s:
        t = s.get(Ticket, ticket_id)
        if t is None:
            return
        c, r = state.classification, state.route
        t.status = state.status
        t.language = state.language
        t.intent = c.intent if c else ""
        t.urgency = c.urgency if c else ""
        t.queue = r.queue if r else ""
        t.priority = r.priority if r else ""
        t.sla_hours = r.sla_hours if r else None
        t.gate_score = state.gate_score
        t.decision = state.decision
        t.final_reply = state.final_reply
        t.state_json = state.model_dump_json()
        t.updated_at = utcnow()
        for k, v in extra.items():
            setattr(t, k, v)
        s.add(t)
        s.commit()


def run_triage(ticket_id: int) -> TicketState:
    """Run TriageFlow for one ticket. Blocking: call it from a worker thread."""
    with session() as s:
        t = s.get(Ticket, ticket_id)
        if t is None:
            raise ValueError(f"ticket {ticket_id} not found")
        t.status = "triaging"
        s.add(t)
        s.commit()
        subject, body = t.subject, t.body

    broker.reset(ticket_id)
    flow = TriageFlow()
    try:
        flow.kickoff(inputs={"ticket_id": ticket_id, "subject": subject, "raw_text": body})
    except Exception as exc:  # surface failures in the UI instead of a silent spinner
        log.error("triage failed for ticket %s: %s", ticket_id, traceback.format_exc())
        flow.state.status = "failed"
        flow.emit("error", "done", f"{type(exc).__name__}: {exc}")
    state = flow.state
    _save_state(ticket_id, state, flow_id=state.id)
    with session() as s:
        audit(s, ticket_id, "agent", f"triaged:{state.decision or state.status}",
              json.dumps({"gate_score": state.gate_score, "reasons": state.gate_reasons}, ensure_ascii=False))
        s.commit()
    broker.publish(ticket_id, {"step": "end", "status": "done", "detail": state.status, "data": {}, "at": ""})
    return state


def run_review(ticket_id: int, action: str, reply: str = "", queue: str = "", reviewer: str = "Reviewer") -> TicketState:
    """Resume a held ticket from its persisted triage state with the human's decision."""
    with session() as s:
        t = s.get(Ticket, ticket_id)
        if t is None:
            raise ValueError(f"ticket {ticket_id} not found")
        if t.status != "pending_review":
            raise ValueError(f"ticket {ticket_id} is {t.status}, not pending review")
        flow_id = t.flow_id
        before = json.loads(t.state_json) if t.state_json else {}

    flow = ReviewFlow()
    flow.kickoff(
        inputs={"review_action": action, "human_reply": reply, "queue_override": queue, "reviewer": reviewer},
        restore_from_state_id=flow_id,
    )
    state = flow.state
    _save_state(ticket_id, state, review_flow_id=state.id)

    agent_draft = (before.get("draft") or {}).get("reply", "")
    with session() as s:
        audit(s, ticket_id, reviewer, f"review:{action}", json.dumps({
            "agent_draft": agent_draft,
            "final_reply": state.final_reply,
            "edited": bool(reply) and reply.strip() != agent_draft.strip(),
            "queue_override": queue or None,
        }, ensure_ascii=False))
        s.commit()
    broker.publish(ticket_id, {"step": "end", "status": "done", "detail": state.status, "data": {}, "at": ""})
    return state


def ticket_detail(ticket_id: int) -> dict | None:
    with session() as s:
        t = s.get(Ticket, ticket_id)
        if t is None:
            return None
        logs = s.exec(select(AuditLog).where(AuditLog.ticket_id == ticket_id).order_by(AuditLog.at)).all()
        return {
            "ticket": t.model_dump(exclude={"state_json"}),
            "state": json.loads(t.state_json) if t.state_json else None,
            "audit": [
                {"at": a.at.isoformat(), "actor": a.actor, "action": a.action,
                 "detail": json.loads(a.detail) if a.detail else {}}
                for a in logs
            ],
        }


# ---------------------------------------------------------------- seed data

def _seed_history(rng: random.Random) -> list[Ticket]:
    """Seven days of already-handled tickets so the Insights view has something to compare.
    Billing Tier 1 surges in the last 24 hours (a bill-run day), which is what the demo shows."""
    daily = {
        "Billing Tier 1": 18, "Billing Tier 2": 4, "Technical Tier 1": 22, "Technical Tier 2": 6,
        "Accounts": 9, "Fraud & Security": 3, "Customer Relations": 4, "General": 5,
    }
    intents = {
        "Billing Tier 1": "billing", "Billing Tier 2": "billing", "Technical Tier 1": "technical",
        "Technical Tier 2": "technical", "Accounts": "account", "Fraud & Security": "fraud",
        "Customer Relations": "complaint", "General": "other",
    }
    now = utcnow()
    rows: list[Ticket] = []
    for day in range(7):
        for q, base in daily.items():
            n = base
            if day == 0 and q == "Billing Tier 1":
                n = int(base * 1.8)      # surge today
            elif day == 0 and q == "Technical Tier 1":
                n = int(base * 0.7)      # quieter today
            n = max(0, n + rng.randint(-2, 2))
            for _ in range(n):
                created = now - timedelta(days=day, minutes=rng.randint(1, 24 * 60 - 1))
                rows.append(Ticket(
                    subject=f"Historical {intents[q]} ticket", body="(seeded history)", customer="History",
                    channel=rng.choice(["email", "chat", "voice"]), created_at=created, updated_at=created,
                    status=rng.choice(["resolved", "auto_sent"]), intent=intents[q], urgency="medium",
                    queue=q, priority="P3", language=rng.choice(["en", "ar"]), seeded_history=True,
                ))
    return rows


def seed(reset: bool = False) -> int:
    with session() as s:
        if reset:
            for row in s.exec(select(AuditLog)).all():
                s.delete(row)
            for row in s.exec(select(Ticket)).all():
                s.delete(row)
            s.commit()
        if s.exec(select(Ticket)).first() is not None:
            return 0
        with open(settings.data_dir / "tickets_seed.yaml", encoding="utf-8") as f:
            demo = yaml.safe_load(f)
        now = utcnow()
        # Demo tickets first (small ids); the first one is the newest, at the top of the inbox.
        for i, d in enumerate(demo):
            s.add(Ticket(subject=d["subject"], body=d["body"].strip(), customer=d["customer"],
                         channel=d["channel"], created_at=now - timedelta(minutes=1 + i)))
        s.commit()
        for row in _seed_history(random.Random(7)):
            s.add(row)
        s.commit()
        return len(demo)


# ---------------------------------------------------------------- insights

def aggregates() -> list[dict]:
    """Per-queue volume: last 24h vs the average day of the previous 6 days, plus staffing."""
    now = utcnow()
    day_ago, week_ago = now - timedelta(days=1), now - timedelta(days=7)
    staffed = queues()
    counts = {q: {"last_24h": 0, "prev": 0} for q in staffed}
    urgency: dict[str, dict[str, int]] = {q: {} for q in staffed}
    with session() as s:
        for t in s.exec(select(Ticket).where(Ticket.created_at >= week_ago, Ticket.queue != "")):
            if t.queue not in counts:
                continue
            bucket = "last_24h" if t.created_at >= day_ago else "prev"
            counts[t.queue][bucket] += 1
            if bucket == "last_24h":
                urgency[t.queue][t.urgency or "medium"] = urgency[t.queue].get(t.urgency or "medium", 0) + 1
    return [
        {
            "queue": q,
            "agents": staffed[q],
            "last_24h": c["last_24h"],
            "daily_avg_prev": round(c["prev"] / 6, 1),
            "change_pct": round(100 * (c["last_24h"] - c["prev"] / 6) / max(1, c["prev"] / 6)),
            "by_urgency": urgency[q],
        }
        for q, c in counts.items()
    ]


def suggest_staffing() -> StaffingSuggestion:
    agg = aggregates()
    if settings.offline:
        return offline.suggest_staffing([dict(r) for r in agg])
    from app.crews.insights.crew import InsightsCrew

    slim = [{k: r[k] for k in ("queue", "agents", "last_24h", "daily_avg_prev", "change_pct")} for r in agg]
    from app.structured import kickoff_structured

    out, _ = kickoff_structured(InsightsCrew().crew(), {"aggregates": json.dumps(slim, indent=2)}, StaffingSuggestion)
    return out

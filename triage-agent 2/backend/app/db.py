"""Application data: tickets and an audit log. SQLite for the demo (one file, zero setup).
The Flow keeps its own persisted state; the ticket row mirrors what the UI lists."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.config import settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Ticket(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    subject: str
    body: str
    customer: str = "Customer"
    channel: str = "email"
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)
    status: str = Field(default="new", index=True)
    language: str = ""
    intent: str = ""
    urgency: str = ""
    queue: str = Field(default="", index=True)
    priority: str = ""
    sla_hours: int | None = None
    gate_score: float | None = None
    decision: str = ""
    final_reply: str = ""
    flow_id: str = ""         # TriageFlow persisted state id
    review_flow_id: str = ""  # ReviewFlow persisted state id
    state_json: str = ""      # latest TicketState, for the detail view
    seeded_history: bool = False  # background volume for the Insights view


class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ticket_id: int = Field(index=True)
    at: datetime = Field(default_factory=utcnow)
    actor: str
    action: str
    detail: str = ""  # JSON


_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def session() -> Session:
    return Session(engine, expire_on_commit=False)


def audit(s: Session, ticket_id: int, actor: str, action: str, detail: str = "") -> None:
    s.add(AuditLog(ticket_id=ticket_id, actor=actor, action=action, detail=detail))


def list_tickets(s: Session, include_history: bool = False) -> list[Ticket]:
    q = select(Ticket).order_by(Ticket.created_at.desc())  # type: ignore[union-attr]
    if not include_history:
        q = q.where(Ticket.seeded_history == False)  # noqa: E712
    return list(s.exec(q))

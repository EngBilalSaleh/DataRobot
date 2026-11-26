"""HTTP API. Each flow step is streamed to the browser over server-sent events.

    uvicorn app.api:app --reload
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import service
from app.config import settings
from app.db import Ticket, init_db, list_tickets, session
from app.events import broker
from app.rag import store
from app.rag.ingest import ensure_ingested
from app.routing import queues


@asynccontextmanager
async def lifespan(_: FastAPI):
    broker.bind_loop(asyncio.get_running_loop())
    init_db()
    await asyncio.to_thread(ensure_ingested)
    service.seed()
    yield


app = FastAPI(title="Ticket Triage Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
)


class NewTicket(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    customer: str = "Customer"
    channel: Literal["email", "chat", "voice"] = "email"


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    reply: str = ""
    queue: str = ""
    reviewer: str = "Reviewer"


def _summary(t: Ticket) -> dict:
    return t.model_dump(exclude={"state_json", "body"}) | {"preview": t.body[:140]}


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "offline": settings.offline,
        "provider": None if settings.offline else "Groq",
        "models": None if settings.offline else {
            "classify": settings.classify_model, "draft": settings.draft_model, "insights": settings.insights_model,
        },
        "llm_ready": settings.offline or bool(settings.groq_api_key),
        "embeddings": settings.embeddings,
        "gate_threshold": settings.gate_threshold,
        "queues": list(queues()),
    }


@app.get("/api/tickets")
def get_tickets() -> list[dict]:
    with session() as s:
        return [_summary(t) for t in list_tickets(s)]


@app.post("/api/tickets", status_code=201)
def post_ticket(body: NewTicket, bg: BackgroundTasks) -> dict:
    t = service.create_ticket(body.subject, body.body, body.customer, body.channel)
    bg.add_task(asyncio.to_thread, service.run_triage, t.id)
    return _summary(t)


@app.get("/api/tickets/{ticket_id}")
def get_ticket(ticket_id: int) -> dict:
    detail = service.ticket_detail(ticket_id)
    if detail is None:
        raise HTTPException(404, "Ticket not found")
    return detail


@app.post("/api/tickets/{ticket_id}/triage", status_code=202)
def triage(ticket_id: int, bg: BackgroundTasks) -> dict:
    with session() as s:
        t = s.get(Ticket, ticket_id)
        if t is None:
            raise HTTPException(404, "Ticket not found")
        if t.status == "triaging":
            raise HTTPException(409, "Ticket is already being triaged")
    bg.add_task(asyncio.to_thread, service.run_triage, ticket_id)
    return {"ticket_id": ticket_id, "status": "triaging"}


@app.get("/api/tickets/{ticket_id}/stream")
async def stream(ticket_id: int) -> StreamingResponse:
    """Replays the steps so far, then streams new ones until the flow ends."""

    async def events():
        q, history = broker.subscribe(ticket_id)
        try:
            for e in history:
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                if e.get("step") == "end":
                    return
            while True:
                try:
                    e = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                if e.get("step") == "end":
                    return
        finally:
            broker.unsubscribe(ticket_id, q)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/tickets/{ticket_id}/review")
async def review(ticket_id: int, body: ReviewRequest) -> dict:
    try:
        await asyncio.to_thread(service.run_review, ticket_id, body.action, body.reply, body.queue, body.reviewer)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return service.ticket_detail(ticket_id) or {}


@app.get("/api/kb/{chunk_id}")
def kb_chunk(chunk_id: str) -> dict:
    chunk = store.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(404, "Passage not found")
    return chunk.model_dump()


@app.get("/api/insights")
def insights() -> dict:
    return {"queues": service.aggregates()}


@app.post("/api/insights/suggest")
async def insights_suggest() -> dict:
    suggestion = await asyncio.to_thread(service.suggest_staffing)
    return suggestion.model_dump()


@app.post("/api/demo/reset")
def demo_reset() -> dict:
    n = service.seed(reset=True)
    return {"seeded": n}

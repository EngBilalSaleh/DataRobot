# Ticket triage agent

An agent that reads, classifies, answers and routes customer support tickets, grounded in a
knowledge base, with a human in the loop where it matters. Built with **CrewAI 1.15.45 Flows**,
LLMs on **Groq**, hybrid **RAG** on Qdrant, **FastAPI** and **Next.js**. English and Arabic.

The data is synthetic and belongs to a fictional operator, "Sahab Telecom". Every policy in
the knowledge base is invented for the demo.

## How it works

```
                  ┌──────────── TriageFlow (CrewAI Flow, @persist) ─────────────┐
ticket ─► ingest ─► classify ─► retrieve ─► draft ─► route ─► gate ─┬─ auto ──► auto_send
          (code)    (agent)     (code+RAG)  (agent)  (code)  (code) └─ review ─► hold ─► ReviewFlow
```

| Step     | Who decides | What happens                                                                                    |
| -------- | ----------- | ----------------------------------------------------------------------------------------------- |
| Ingest   | Code        | Redacts phone, email, IBAN, card and national ID numbers; detects Arabic or English             |
| Classify | Agent       | ClassifyCrew returns intent, product, urgency, sentiment, confidence and risk flags             |
| Retrieve | Code + RAG  | Hybrid search (multilingual dense + BM25, fused) over KB articles and resolved tickets          |
| Draft    | Agent       | ResolveCrew writes a cited reply in the customer's language; a guardrail rejects uncited drafts |
| Route    | Code        | `data/routing_rules.yaml` maps the classification to queue, priority and SLA                    |
| Gate     | Code        | Blends confidence with retrieval relevance; risk flags, anger or no citations force review      |
| Review   | Human       | `ReviewFlow` resumes the persisted state (`restore_from_state_id`) with the human's edit        |

**The agent proposes. The Flow decides the queue. The contact center decides the person.**

## Quick start (local)

Requirements: Python 3.11 to 3.13, Node 20+.

```bash
cp .env.example .env              # add GROQ_API_KEY, or set OFFLINE_MODE=true

# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m uvicorn app.api:app --reload     # http://localhost:8000 ; ingests the KB and seeds tickets on first start

# frontend (second terminal)
cd frontend
npm install
npm run dev                       # http://localhost:3000
```

No API key? Set `OFFLINE_MODE=true` and `EMBEDDINGS=hash` in `.env`. The whole app then runs
with heuristic stand-ins for the crews, and the header shows "Offline mode".

## Docker

```bash
cp .env.example .env    # fill in a key
docker compose up --build
```

Opens the console on http://localhost:3000, the API on http://localhost:8000 and Qdrant on 6333.

## Evaluation

```bash
cd backend
python -m eval.run_eval            # writes eval/report.md and eval/results.jsonl
```

Runs the Flow over 40 hand-labeled tickets (24 English, 16 Arabic)

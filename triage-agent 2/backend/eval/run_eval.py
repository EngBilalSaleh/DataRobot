"""Run the triage Flow over the labeled set and report the numbers for the deck.

    python -m eval.run_eval              # uses OFFLINE_MODE / model settings from the environment
    python -m eval.run_eval --limit 10   # quick smoke run

Writes eval/report.md and eval/results.jsonl.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import yaml

from app.config import settings
from app.flows.triage import TriageFlow
from app.rag import store
from app.rag.ingest import ensure_ingested

HERE = Path(__file__).parent


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}% ({n}/{d})" if d else "n/a"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    ensure_ingested()
    rows = yaml.safe_load((HERE / "labeled.yaml").read_text(encoding="utf-8"))
    if args.limit:
        rows = rows[: args.limit]

    results = []
    for i, row in enumerate(rows, start=1):
        t0 = time.perf_counter()
        flow = TriageFlow()
        try:
            flow.kickoff(inputs={"ticket_id": -i, "subject": "", "raw_text": row["text"]})
            error = ""
        except Exception as exc:  # keep going; count it as a miss
            error = f"{type(exc).__name__}: {exc}"
        s = flow.state
        c = s.classification
        citations = s.draft.citations if s.draft else []
        valid = [x for x in citations if store.get_chunk(x) is not None]
        results.append({
            "lang": row["lang"], "text": row["text"],
            "gold_intent": row["intent"], "gold_urgency": row["urgency"], "gold_queue": row["queue"],
            "gold_risk": row.get("risk", []),
            "intent": c.intent if c else None, "urgency": c.urgency if c else None,
            "risk": c.risk_flags if c else [], "queue": s.route.queue if s.route else None,
            "decision": s.decision, "gate_score": s.gate_score,
            "citations": citations, "grounded": bool(valid) and len(valid) == len(citations),
            "seconds": round(time.perf_counter() - t0, 2), "error": error,
        })
        print(f"[{i}/{len(rows)}] {row['lang']} {row['intent']:>9} -> {results[-1]['intent']} | {results[-1]['queue']} | {s.decision}")

    n = len(results)
    queue_ok = [r for r in results if r["queue"] == r["gold_queue"]]
    intent_ok = [r for r in results if r["intent"] == r["gold_intent"]]
    auto = [r for r in results if r["decision"] == "auto"]
    auto_ok = [r for r in auto if r["queue"] == r["gold_queue"]]
    risky = [r for r in results if r["gold_risk"]]
    risky_held = [r for r in risky if r["decision"] == "review"]
    drafts = [r for r in results if r["citations"]]
    grounded = [r for r in results if r["grounded"]]
    errors = [r for r in results if r["error"]]
    secs = [r["seconds"] for r in results if not r["error"]]

    by_lang = {
        lang: pct(sum(1 for r in results if r["lang"] == lang and r["queue"] == r["gold_queue"]),
                  sum(1 for r in results if r["lang"] == lang))
        for lang in ("en", "ar")
    }
    mode = "offline heuristics" if settings.offline else f"{settings.classify_model} / {settings.draft_model}"
    report = f"""# Evaluation report

Mode: {mode}. Embeddings: {settings.embeddings}. Gate threshold: {settings.gate_threshold}. Tickets: {n}.

| Metric | Result |
|---|---|
| Routing accuracy (queue) | {pct(len(queue_ok), n)} |
| Intent accuracy | {pct(len(intent_ok), n)} |
| Routing accuracy, English | {by_lang['en']} |
| Routing accuracy, Arabic | {by_lang['ar']} |
| Sent automatically | {pct(len(auto), n)} |
| Precision of auto-sent tickets (correct queue) | {pct(len(auto_ok), len(auto))} |
| Risky tickets held for review | {pct(len(risky_held), len(risky))} |
| Drafts fully grounded in real sources | {pct(len(grounded), n)} |
| Median seconds per ticket | {statistics.median(secs) if secs else 'n/a'} |
| Errors | {len(errors)} |

Precision of auto-sent tickets matters more than the auto-send rate: raise GATE_THRESHOLD
until it is where the customer wants it, and accept that fewer tickets go out automatically.
"""
    (HERE / "report.md").write_text(report, encoding="utf-8")
    with open(HERE / "results.jsonl", "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\n" + report)


if __name__ == "__main__":
    main()

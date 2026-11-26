"""Deterministic routing and the confidence gate.

The classify agent proposes; this module decides. Keeping it in code makes every routing
decision explainable ("rule billing-urgent matched") and lets the customer's existing
business rules drop in unchanged.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from app.config import settings
from app.models import Classification, Draft, Route


@lru_cache(maxsize=1)
def load_rules() -> dict[str, Any]:
    with open(settings.data_dir / "routing_rules.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def queues() -> dict[str, int]:
    return dict(load_rules()["queues"])


def _as_list(value: Any) -> list[str]:
    return value if isinstance(value, list) else [value]


def _matches(when: dict[str, Any], c: Classification) -> bool:
    if "intent" in when and c.intent not in _as_list(when["intent"]):
        return False
    if "urgency" in when and c.urgency not in _as_list(when["urgency"]):
        return False
    if "product" in when and c.product not in _as_list(when["product"]):
        return False
    if "risk_flag" in when and not set(_as_list(when["risk_flag"])) & set(c.risk_flags):
        return False
    return True


def route(c: Classification) -> Route:
    for rule in load_rules()["rules"]:
        if _matches(rule.get("when") or {}, c):
            return Route(**rule["route"], rule=rule["name"])
    raise ValueError("routing_rules.yaml needs a catch-all rule with an empty 'when'")


def gate(
    c: Classification,
    draft: Draft | None,
    top_relevance: float,
    threshold: float | None = None,
) -> tuple[float, str, list[str]]:
    """Combine signals into one score and decide auto-send vs human review.

    A model's self-reported confidence is one signal, never the decision. The score blends
    classifier confidence with how relevant the best knowledge chunk was; hard rules then
    force review for anything risky, whatever the score.
    """
    threshold = settings.gate_threshold if threshold is None else threshold
    score = round(0.6 * c.confidence + 0.4 * max(0.0, min(1.0, top_relevance)), 3)
    reasons: list[str] = []

    if c.risk_flags:
        reasons.append(f"risk flag: {', '.join(c.risk_flags)}")
    if c.urgency == "critical":
        reasons.append("critical urgency")
    if c.sentiment == "angry":
        reasons.append("angry customer")
    if draft is None or not draft.citations:
        reasons.append("draft has no citations")
    if score < threshold:
        reasons.append(f"score {score:.2f} below threshold {threshold:.2f}")

    decision = "review" if reasons else "auto"
    if decision == "auto":
        reasons.append(f"score {score:.2f} at or above threshold {threshold:.2f}, no risk flags")
    return score, decision, reasons

"""Heuristic stand-ins for the three crews, used when OFFLINE_MODE=true.

They exist so the whole application (flow, routing, gate, review, UI, evaluation) runs with
no API key, and as a safety net for a live demo. They are deliberately simple and are
labelled as offline everywhere they surface. The real system uses the CrewAI crews.
"""

from __future__ import annotations

import re

from app.models import Chunk, Classification, Draft, StaffingMove, StaffingSuggestion

_KEYWORDS: dict[str, list[str]] = {
    "fraud": ["fraud", "unauthori", "did not make", "didn't make", "not me", "stolen", "hacked", "otp",
              "sim swap", "scam", "without my", "asking for my code", "asked me for the code", "for the code", "احتيال", "بدون علمي", "سرقة", "اختراق", "لم أقم", "رمز التحقق"],
    "billing": ["bill", "charge", "charged", "invoice", "payment", "paid", "refund", "roaming", "vat", "sar",
                "فاتورة", "الفاتورة", "رسوم", "مبلغ", "سداد", "دفع", "تجوال", "استرجاع"],
    "technical": ["internet", "fiber", "slow", "no service", "signal", "esim", "router", "down", "not working",
                  "connection", "data", "does not work", "doesn't work", "activation", "إنترنت", "الإنترنت", "الألياف", "بطيء", "بطء", "شبكة", "مقطوع", "الراوتر"],
    "account": ["account", "password", "plan", "upgrade", "downgrade", "transfer", "ownership", "login", "sign in",
                "كلمة المرور", "الباقة", "باقتي", "ترقية", "تخفيض", "نقل", "ملكية", "تسجيل الدخول"],
    "complaint": ["complaint", "unacceptable", "third time", "nobody", "terrible", "worst", "escalate",
                  "شكوى", "غير مقبول", "سيئة", "تصعيد", "للمرة الثالثة"],
}
_PRODUCT = {
    "wallet": ["wallet", "sahab pay", "محفظ", "سحاب باي"],
    "home_fiber": ["fiber", "fibre", "router", "home internet", "الألياف", "الراوتر", "المنزلي"],
    "mobile_prepaid": ["prepaid", "recharge", "مسبق الدفع", "شحن"],
    "mobile_postpaid": ["bill", "plan", "roaming", "esim", "data", "فاتورة", "الباقة", "تجوال", "بيانات"],
}
_ANGRY = ["unacceptable", "ridiculous", "furious", "worst", "!!", "غير مقبول", "فوراً", "سيئة جداً"]
_NEGATIVE = ["not happy", "disappointed", "again", "still", "مستاء", "للأسف", "مرة أخرى"]
_HIGH = ["urgent", "immediately", "asap", "down", "no internet", "cannot", "can't", "فوراً", "عاجل", "مقطوع", "لا يعمل"]
_LEGAL = ["lawyer", "court", "lawsuit", "legal action", "محامي", "محكمة", "قضية"]
_REGULATOR = ["cst", "regulator", "citc", "الهيئة", "هيئة الاتصالات"]


def _count(text: str, words: list[str]) -> int:
    # Latin keywords must start at a word boundary ("vat" must not match "activation");
    # Arabic keywords match as substrings because of attached prefixes (ال، و، ب).
    return sum(
        1 for w in words
        if (re.search(rf"\b{re.escape(w)}", text) if w.isascii() else w in text)
    )


def classify(text: str, subject: str = "") -> Classification:
    t = f"{subject} {text}".lower()
    scores = {intent: _count(t, words) for intent, words in _KEYWORDS.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (intent, best), (_, second) = ranked[0], ranked[1]
    if best == 0:
        intent = "other"
    # Fraud wins over billing when both appear: money taken without consent is a fraud case.
    if scores["fraud"] and scores["fraud"] >= 1 and intent == "billing":
        intent = "fraud"

    product = next((p for p, words in _PRODUCT.items() if _count(t, words)), "general")
    angry = _count(t, _ANGRY) > 0
    sentiment = "angry" if angry else ("negative" if _count(t, _NEGATIVE) else "neutral")
    urgency = "high" if _count(t, _HIGH) else "medium"
    if intent == "fraud":
        urgency = "critical" if angry else "high"
    if intent == "other":
        urgency = "low"

    risk: list[str] = []
    if intent == "fraud":
        risk.append("fraud")
    if _count(t, _LEGAL):
        risk.append("legal")
    if _count(t, _REGULATOR):
        risk.append("regulator")

    margin = best - second
    confidence = 0.5 if best == 0 else min(0.95, 0.6 + 0.1 * best + 0.05 * margin)
    if margin == 0 and best > 0:
        confidence = 0.55

    return Classification(
        intent=intent,  # type: ignore[arg-type]
        product=product,
        urgency=urgency,  # type: ignore[arg-type]
        sentiment=sentiment,  # type: ignore[arg-type]
        confidence=round(confidence, 2),
        risk_flags=risk,  # type: ignore[arg-type]
        summary=f"[offline] Customer ticket about {intent} ({product}).",
    )


def _first_sentences(text: str, n: int = 2) -> str:
    parts = re.split(r"(?<=[.!؟?])\s+", text.replace("\n", " ").strip())
    return " ".join(parts[:n])


def draft(c: Classification, context: list[Chunk], language: str) -> Draft:
    kb = [ch for ch in context if ch.source == "kb" and ch.lang == language] or [ch for ch in context if ch.source == "kb"]
    if not kb:
        body = "A specialist will review your request and reply shortly." if language == "en" else "سيقوم أحد المختصين بمراجعة طلبك والرد عليك قريباً."
        return Draft(reply=body, citations=[], language=language)  # type: ignore[arg-type]
    top = kb[0]
    if language == "ar":
        reply = f"شكراً لتواصلك مع سحاب. {_first_sentences(top.text)} إذا احتجت أي مساعدة إضافية فنحن هنا لخدمتك."
    else:
        reply = f"Thank you for contacting Sahab. {_first_sentences(top.text)} If anything is still unclear, reply here and we will help."
    return Draft(reply=reply, citations=[top.id], language=language)  # type: ignore[arg-type]


def suggest_staffing(aggregates: list[dict]) -> StaffingSuggestion:
    """Move one agent from the queue whose load per agent dropped most to the one that rose most."""
    rows = [r for r in aggregates if r["agents"] > 0]
    for r in rows:
        r["load_now"] = r["last_24h"] / r["agents"]
        r["load_before"] = r["daily_avg_prev"] / r["agents"]
    rising = sorted(rows, key=lambda r: r["load_now"] - r["load_before"], reverse=True)
    donors = [r for r in reversed(rising) if r["queue"] != "Fraud & Security" and r["agents"] > 1]
    if not rising or not donors or rising[0]["last_24h"] <= rising[0]["daily_avg_prev"] * 1.2:
        return StaffingSuggestion(summary="[offline] Volumes are within normal range; no moves needed.")
    to_q, from_q = rising[0], donors[0]
    if to_q["queue"] == from_q["queue"]:
        return StaffingSuggestion(summary="[offline] Only one queue is changing; no moves needed.")
    pct = round(100 * (to_q["last_24h"] - to_q["daily_avg_prev"]) / max(1, to_q["daily_avg_prev"]))
    return StaffingSuggestion(
        summary=f"[offline] {to_q['queue']} volume is up {pct}% against the previous 6-day average.",
        moves=[
            StaffingMove(
                from_queue=from_q["queue"],
                to_queue=to_q["queue"],
                agents=1,
                reason=f"{from_q['queue']} load per agent is lowest; {to_q['queue']} is rising fastest.",
            )
        ],
    )

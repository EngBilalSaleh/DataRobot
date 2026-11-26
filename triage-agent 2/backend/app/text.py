"""Deterministic text steps: PII redaction and language detection.

Plain code on purpose: these must behave the same way every time, and no model should
see personal data. Demo scope: regex patterns for the common identifiers in Saudi
telecom and banking tickets. Names are not redacted; a production build would add an
NER-based redactor (e.g. Presidio) with Arabic support.
"""

from __future__ import annotations

import re

# Order matters: longer, more specific patterns first.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("IBAN", re.compile(r"\bSA\d{2}(?:\s?[0-9A-Z]{4}){5}\b", re.IGNORECASE)),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("PHONE", re.compile(r"(?:\+?966|00966|\b0)5\d(?:[ -]?\d){7}\b")),
    ("NATIONAL_ID", re.compile(r"\b[12]\d{9}\b")),
]

_ARABIC = re.compile(r"[\u0600-\u06FF]")
_LATIN = re.compile(r"[A-Za-z]")
# Arabic-Indic and Eastern Arabic-Indic digits -> Western, so patterns and numbers match.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_digits(text: str) -> str:
    return text.translate(_DIGITS)


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Replace personal identifiers with typed placeholders. Returns text and counts by type."""
    counts: dict[str, int] = {}
    out = normalize_digits(text)
    for label, pattern in _PATTERNS:
        out, n = pattern.subn(f"[{label}]", out)
        if n:
            counts[label] = counts.get(label, 0) + n
    return out, counts


def detect_language(text: str) -> str:
    """'ar' when Arabic letters dominate the Latin ones, else 'en'. Good enough for two languages."""
    ar = len(_ARABIC.findall(text))
    la = len(_LATIN.findall(text))
    return "ar" if ar > la else "en"

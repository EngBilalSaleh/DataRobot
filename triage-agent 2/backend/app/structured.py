"""Run a crew and always come back with the typed model, or a clear error.

Some open-weight models served on Groq (notably gpt-oss) occasionally return their final
answer as a call to a tool named "json" instead of plain content. Groq validates tool calls
against the request, rejects that call with a 400 `tool_use_failed`, and puts the model's
output in `failed_generation`. The answer itself is usually correct, so rather than failing the
ticket we recover it and validate it against the same Pydantic schema. Anything that does not
validate still raises.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar

from json_repair import repair_json
from pydantic import BaseModel, ValidationError

log = logging.getLogger("triage")
M = TypeVar("M", bound=BaseModel)


def _as_dict(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(repair_json(value))
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _failed_generation(exc: BaseException) -> str | None:
    """Find Groq's failed_generation in the exception or anything it wraps."""
    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        body = getattr(e, "body", None)
        if isinstance(body, dict):
            err = body.get("error", body)
            if isinstance(err, dict) and err.get("failed_generation"):
                return str(err["failed_generation"])
        m = re.search(r"'failed_generation':\s*'(.*)'\}", str(e), re.S)
        if m:
            return m.group(1)
        e = e.__cause__ or e.__context__
    return None


def salvage(exc: BaseException, model: type[M]) -> M | None:
    """Rebuild the model from a rejected tool call, or return None if there is nothing usable."""
    raw = _failed_generation(exc)
    payload = _as_dict(raw)
    if payload is None:
        return None
    # {"name": "json", "arguments": {...}} or the object itself
    candidate = _as_dict(payload.get("arguments")) if "arguments" in payload else payload
    if candidate is None:
        return None
    try:
        return model.model_validate(candidate)
    except ValidationError:
        return None


def kickoff_structured(crew: Any, inputs: dict, model: type[M]) -> tuple[M, bool]:
    """Kick off the crew and return (typed output, recovered). recovered is True when the output
    came from a rejected tool call; the caller should re-check anything a guardrail would."""
    try:
        result = crew.kickoff(inputs=inputs)
    except Exception as exc:
        recovered = salvage(exc, model)
        if recovered is None:
            raise
        log.warning("Recovered %s from a rejected 'json' tool call: %s", model.__name__, str(exc)[:200])
        return recovered, True

    out = getattr(result, "pydantic", None)
    if isinstance(out, model):
        return out, False
    for candidate in (getattr(result, "json_dict", None), getattr(result, "raw", None)):
        data = _as_dict(candidate)
        if data is not None:
            try:
                return model.model_validate(data), False
            except ValidationError:
                continue
    raise ValueError(f"The crew did not return a valid {model.__name__}: {str(getattr(result, 'raw', ''))[:300]}")

"""Runtime settings, read once from the environment (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]  # repo root (triage-agent/)
DEFAULT_DATA_DIR = ROOT / "data"


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # When true, the flow runs end to end with heuristic stand-ins instead of LLM calls.
    # Useful with no API key, in tests, and as a demo safety net. The UI shows a banner.
    offline: bool = field(default_factory=lambda: _bool("OFFLINE_MODE"))

    # LLMs run on Groq through its OpenAI-compatible API. Model IDs are Groq's own, see
    # https://console.groq.com/docs/models . A small, fast model classifies; a stronger one drafts.
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_base_url: str = field(default_factory=lambda: os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"))
    classify_model: str = field(default_factory=lambda: os.getenv("CLASSIFY_MODEL", "openai/gpt-oss-20b"))
    draft_model: str = field(default_factory=lambda: os.getenv("DRAFT_MODEL", "openai/gpt-oss-120b"))
    insights_model: str = field(default_factory=lambda: os.getenv("INSIGHTS_MODEL", "openai/gpt-oss-20b"))

    # Give the drafting agent the knowledge-search tool for follow-up lookups. Off by default:
    # the Flow already retrieves the passages, and some Groq models (gpt-oss) answer with a
    # stray "json" tool call when tools are present, which Groq rejects.
    resolve_use_tool: bool = field(default_factory=lambda: _bool("RESOLVE_USE_TOOL"))

    # "fastembed" (multilingual dense + BM25 sparse, downloads models on first run)
    # or "hash" (dependency-free, offline; fine for tests and a no-network demo).
    embeddings: str = field(default_factory=lambda: os.getenv("EMBEDDINGS", "fastembed"))
    dense_model: str = field(
        default_factory=lambda: os.getenv(
            "DENSE_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    )

    # Qdrant: a server URL (docker compose sets this) or a local folder.
    qdrant_url: str | None = field(default_factory=lambda: os.getenv("QDRANT_URL") or None)
    qdrant_path: str = field(default_factory=lambda: os.getenv("QDRANT_PATH", str(ROOT / ".qdrant")))

    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'triage.db'}")
    )
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", str(DEFAULT_DATA_DIR))))

    # Gate: score >= threshold and no risk flags -> auto-send; otherwise human review.
    gate_threshold: float = field(default_factory=lambda: float(os.getenv("GATE_THRESHOLD", "0.75")))

    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    )


settings = Settings()

# CrewAI sends anonymous telemetry by default; keep the demo quiet and private.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

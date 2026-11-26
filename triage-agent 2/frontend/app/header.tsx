"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Health } from "@/lib/api";

export function Header() {
  const path = usePathname();
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setError(true));
  }, []);

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <span className="brand-name">Triage desk</span>
        <span className="brand-org">Sahab Telecom support</span>
      </div>
      <nav className="nav" aria-label="Main">
        <Link href="/" aria-current={path === "/" ? "page" : undefined}>Inbox</Link>
        <Link href="/insights" aria-current={path === "/insights" ? "page" : undefined}>Insights</Link>
      </nav>
      <div className="runtime">
        {error && <span className="pill pill-risk">API not reachable on {process.env.NEXT_PUBLIC_API_URL ?? "localhost:8000"}</span>}
        {health?.offline && (
          <span className="pill pill-warn" title="Heuristic stand-ins replace the LLM crews. Set OFFLINE_MODE=false and a model API key for the real agent.">
            Offline mode: no LLM calls
          </span>
        )}
        {health && !health.offline && !health.llm_ready && (
          <span className="pill pill-risk">GROQ_API_KEY is not set</span>
        )}
        {health && !health.offline && health.models && (
          <span className="runtime-models" title="Models per task, served by Groq">
            Groq: {health.models.classify.split("/").pop()} classifies, {health.models.draft.split("/").pop()} drafts
          </span>
        )}
      </div>
    </header>
  );
}

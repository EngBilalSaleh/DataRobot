export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Status = "new" | "triaging" | "auto_sent" | "pending_review" | "resolved" | "rejected" | "failed";

export interface TicketSummary {
  id: number;
  subject: string;
  preview: string;
  customer: string;
  channel: string;
  created_at: string;
  status: Status;
  language: string;
  intent: string;
  urgency: string;
  queue: string;
  priority: string;
  sla_hours: number | null;
  gate_score: number | null;
  decision: string;
  final_reply: string;
}

export interface TraceEvent {
  step: string;
  status: "started" | "done" | "info";
  detail: string;
  data: Record<string, unknown>;
  at: string;
}

export interface Classification {
  intent: string;
  product: string;
  urgency: string;
  sentiment: string;
  confidence: number;
  risk_flags: string[];
  summary: string;
}

export interface Chunk { id: string; title: string; text: string; lang: string; source: "kb" | "resolved"; score: number }

export interface TicketState {
  redacted: string;
  redactions: Record<string, number>;
  language: string;
  classification: Classification | null;
  context: Chunk[];
  top_relevance: number;
  draft: { reply: string; citations: string[]; language: string } | null;
  route: { queue: string; priority: string; sla_hours: number; rule: string } | null;
  gate_score: number;
  gate_reasons: string[];
  decision: "auto" | "review" | "";
  status: Status;
  final_reply: string;
  trace: TraceEvent[];
}

export interface AuditEntry { at: string; actor: string; action: string; detail: Record<string, unknown> }

export interface TicketDetail {
  ticket: TicketSummary & { body: string };
  state: TicketState | null;
  audit: AuditEntry[];
}

export interface Health {
  offline: boolean;
  provider: string | null;
  llm_ready: boolean;
  models: Record<string, string> | null;
  embeddings: string;
  gate_threshold: number;
  queues: string[];
}

export interface QueueStats {
  queue: string;
  agents: number;
  last_24h: number;
  daily_avg_prev: number;
  change_pct: number;
  by_urgency: Record<string, number>;
}

export interface Suggestion { summary: string; moves: { from_queue: string; to_queue: string; agents: number; reason: string }[] }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { msg = (await res.json()).detail ?? msg; } catch { /* keep status text */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<Health>("/api/health"),
  tickets: () => req<TicketSummary[]>("/api/tickets"),
  ticket: (id: number) => req<TicketDetail>(`/api/tickets/${id}`),
  create: (body: { subject: string; body: string; customer: string; channel: string }) =>
    req<TicketSummary>("/api/tickets", { method: "POST", body: JSON.stringify(body) }),
  triage: (id: number) => req<{ status: string }>(`/api/tickets/${id}/triage`, { method: "POST" }),
  review: (id: number, body: { action: "approve" | "reject"; reply?: string; queue?: string; reviewer?: string }) =>
    req<TicketDetail>(`/api/tickets/${id}/review`, { method: "POST", body: JSON.stringify(body) }),
  chunk: (id: string) => req<Chunk>(`/api/kb/${encodeURIComponent(id)}`),
  insights: () => req<{ queues: QueueStats[] }>("/api/insights"),
  suggest: () => req<Suggestion>("/api/insights/suggest", { method: "POST" }),
  reset: () => req<{ seeded: number }>("/api/demo/reset", { method: "POST" }),
  streamUrl: (id: number) => `${API}/api/tickets/${id}/stream`,
};

export const STATUS_LABEL: Record<Status, string> = {
  new: "New",
  triaging: "Triaging",
  auto_sent: "Auto-sent",
  pending_review: "Needs review",
  resolved: "Resolved",
  rejected: "Draft rejected",
  failed: "Failed",
};

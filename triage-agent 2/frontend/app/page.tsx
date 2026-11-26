"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  STATUS_LABEL,
  type AuditEntry,
  type Chunk,
  type Classification,
  type Health,
  type Status,
  type TicketDetail,
  type TicketState,
  type TicketSummary,
  type TraceEvent,
} from "@/lib/api";

/* ------------------------------------------------------------------ shared bits */

const STEPS = [
  { key: "ingest", name: "Ingest and redact", kind: "code" },
  { key: "classify", name: "Classify", kind: "agent" },
  { key: "retrieve", name: "Retrieve knowledge", kind: "code" },
  { key: "draft", name: "Draft reply", kind: "agent" },
  { key: "route", name: "Route", kind: "code" },
  { key: "gate", name: "Confidence gate", kind: "code" },
  { key: "outcome", name: "Outcome", kind: "result" },
] as const;
const OUTCOME_STEPS = new Set(["send", "hold", "review", "error"]);

type Tone = "ok" | "warn" | "risk" | "neutral" | "agent";
const pill = (tone: Tone, text: string, key?: string) => <span key={key} className={`pill pill-${tone}`}>{text}</span>;

function statusPill(status: Status) {
  const tone: Tone =
    status === "auto_sent" || status === "resolved" ? "ok"
    : status === "pending_review" ? "warn"
    : status === "failed" || status === "rejected" ? "risk"
    : status === "triaging" ? "agent" : "neutral";
  return pill(tone, STATUS_LABEL[status]);
}

const urgencyTone = (u: string): Tone => (u === "critical" ? "risk" : u === "high" ? "warn" : u === "low" ? "ok" : "neutral");
const sentimentTone = (s: string): Tone => (s === "angry" ? "risk" : s === "negative" ? "warn" : s === "positive" ? "ok" : "neutral");
const nice = (s: string) => s.replace(/_/g, " ");

function timeAgo(iso: string) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
}

/* ------------------------------------------------------------------ view model
   The centre panel renders the same findings whether they come from the finished,
   persisted state or from live trace events, so cards fill in as each step finishes. */

interface Findings {
  classification: Classification | null;
  sources: { id: string; title: string; source: string; score: number }[] | null;
  relevance: number | null;
  draft: { reply: string; citations: string[]; language: string } | null;
  route: { queue: string; priority: string; sla_hours: number; rule: string } | null;
  gate: { score: number; decision: string; reasons: string[] } | null;
}

function fromState(s: TicketState): Findings {
  return {
    classification: s.classification,
    sources: s.context.length ? s.context.map((c: Chunk) => ({ id: c.id, title: c.title, source: c.source, score: c.score })) : null,
    relevance: s.context.length ? s.top_relevance : null,
    draft: s.draft,
    route: s.route,
    gate: s.decision ? { score: s.gate_score, decision: s.decision, reasons: s.gate_reasons } : null,
  };
}

function fromEvents(events: TraceEvent[]): Findings {
  const done = (step: string) => [...events].reverse().find((e) => e.step === step && e.status === "done");
  const c = done("classify"), r = done("retrieve"), d = done("draft"), ro = done("route"), g = done("gate");
  const rel = r?.detail.match(/relevance ([\d.]+)/);
  return {
    classification: (c?.data as unknown as Classification) ?? null,
    sources: (r?.data.chunks as Findings["sources"]) ?? null,
    relevance: rel ? Number(rel[1]) : null,
    draft: (d?.data as unknown as Findings["draft"]) ?? null,
    route: (ro?.data as unknown as Findings["route"]) ?? null,
    gate: g ? { score: g.data.score as number, decision: g.data.decision as string, reasons: g.data.reasons as string[] } : null,
  };
}

/* ------------------------------------------------------------------ page */

export default function Inbox() {
  const [health, setHealth] = useState<Health | null>(null);
  const [tickets, setTickets] = useState<TicketSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<TicketDetail | null>(null);
  const [live, setLive] = useState<TraceEvent[] | null>(null);
  const [error, setError] = useState("");
  const [composing, setComposing] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  const loadList = useCallback(() => api.tickets().then(setTickets).catch((e) => setError(e.message)), []);
  const loadDetail = useCallback((id: number) => api.ticket(id).then(setDetail).catch((e) => setError(e.message)), []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => undefined);
    loadList();
  }, [loadList]);

  useEffect(() => {
    if (selected === null && tickets.length) setSelected(tickets[0].id);
  }, [tickets, selected]);

  const stopStream = () => {
    sourceRef.current?.close();
    sourceRef.current = null;
  };

  const startStream = useCallback(
    (id: number) => {
      stopStream();
      setLive([]);
      const es = new EventSource(api.streamUrl(id));
      sourceRef.current = es;
      es.onmessage = (msg) => {
        const event = JSON.parse(msg.data) as TraceEvent;
        if (event.step === "end") {
          stopStream();
          loadDetail(id).then(() => setLive(null));
          loadList();
          return;
        }
        setLive((prev) => [...(prev ?? []), event]);
      };
      es.onerror = () => {
        stopStream();
        setLive(null);
        loadDetail(id);
      };
    },
    [loadDetail, loadList],
  );

  useEffect(() => {
    if (selected === null) return;
    stopStream();
    setLive(null);
    setDetail(null);
    setError("");
    api.ticket(selected).then((d) => {
      setDetail(d);
      if (d.ticket.status === "triaging") startStream(selected);
    }).catch((e) => setError(e.message));
    return stopStream;
  }, [selected, startStream]);

  const runTriage = async (id: number) => {
    setError("");
    try {
      await api.triage(id);
      setTickets((ts) => ts.map((t) => (t.id === id ? { ...t, status: "triaging" } : t)));
      setDetail((d) => (d ? { ...d, ticket: { ...d.ticket, status: "triaging" } } : d));
      startStream(id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const events = live ?? detail?.state?.trace ?? [];
  const findings = useMemo<Findings | null>(
    () => (live ? fromEvents(live) : detail?.state ? fromState(detail.state) : null),
    [live, detail],
  );

  return (
    <main className="desk">
      <section className="col" aria-label="Tickets">
        <div className="list-head">
          <h1>Inbox <span className="muted">({tickets.length})</span></h1>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn" onClick={() => setComposing((c) => !c)} aria-expanded={composing}>
              {composing ? "Close" : "New ticket"}
            </button>
            <button className="btn" title="Restore the seven demo tickets"
              onClick={async () => { await api.reset(); setSelected(null); setDetail(null); loadList(); }}>
              Reset demo
            </button>
          </div>
        </div>
        {composing && <Composer onCreated={(t) => { setComposing(false); setTickets((ts) => [t, ...ts]); setSelected(t.id); }} />}
        <ul className="tickets">
          {tickets.map((t) => (
            <li key={t.id}>
              <button className="ticket-row" aria-current={t.id === selected} onClick={() => setSelected(t.id)}>
                <span className="row-top">
                  <span>#{t.id} · {t.customer} · {t.channel}</span>
                  <span>{timeAgo(t.created_at)}</span>
                </span>
                <span className="subject" dir="auto">{t.subject}</span>
                <span className="preview" dir="auto">{t.preview}</span>
                <span className="meta">
                  {statusPill(t.status)}
                  {t.queue && pill("neutral", t.queue)}
                  {t.priority && pill(t.priority === "P1" ? "risk" : "neutral", t.priority)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="col center" aria-label="Ticket and agent findings">
        {error && <p className="error banner-error">{error}</p>}
        {detail ? (
          <div className="ticket-view">
            <header className="ticket-head">
              <div className="ticket-meta">
                <span className="mono">#{detail.ticket.id}</span>
                <span>{detail.ticket.customer}</span>
                <span>via {detail.ticket.channel}</span>
                {statusPill(live ? "triaging" : detail.ticket.status)}
              </div>
              <h2 dir="auto">{detail.ticket.subject}</h2>
            </header>
            <blockquote className="message" dir="auto">{detail.ticket.body}</blockquote>

            {detail.ticket.status === "new" && !live ? (
              <div className="cta">
                <div>
                  <h3>Not triaged yet</h3>
                  <p className="muted">The agent will redact personal data, classify the ticket, find the right knowledge, draft a reply and decide whether a human needs to review it.</p>
                </div>
                <button className="btn btn-primary" onClick={() => runTriage(detail.ticket.id)}>Run triage</button>
              </div>
            ) : (
              findings && (
                <FindingsView
                  findings={findings}
                  detail={detail}
                  health={health}
                  live={!!live}
                  onReviewed={(d) => { setDetail(d); loadList(); }}
                />
              )
            )}
          </div>
        ) : (
          <div className="empty">
            <h2>Select a ticket</h2>
            <p>Pick a ticket on the left to see what the agent found, or create a new one.</p>
          </div>
        )}
      </section>

      <aside className="col side" aria-label="Agent trace">
        {detail && (
          <>
            <TracePanel events={events} live={!!live} />
            {detail.state?.redacted && Object.keys(detail.state.redactions).length > 0 && (
              <section className="side-block">
                <h3 className="section-title">What the agent saw</h3>
                <p className="redacted" dir="auto">{detail.state.redacted}</p>
              </section>
            )}
            {detail.audit.length > 0 && <Audit entries={detail.audit} />}
          </>
        )}
      </aside>
    </main>
  );
}

/* ------------------------------------------------------------------ centre: findings */

function Pending({ label }: { label: string }) {
  return <div className="pending">{label}</div>;
}

function FindingsView({ findings, detail, health, live, onReviewed }: {
  findings: Findings;
  detail: TicketDetail;
  health: Health | null;
  live: boolean;
  onReviewed: (d: TicketDetail) => void;
}) {
  const { classification: c, route, gate, draft, sources } = findings;
  const status = detail.ticket.status;
  const threshold = health?.gate_threshold ?? 0.75;
  const failed = status === "failed" && !live;

  return (
    <div className="findings">
      <OutcomeBanner gate={gate} status={live ? "triaging" : status} threshold={threshold} failed={failed} />

      <section className="card">
        <div className="card-head">
          <h3>Classification</h3>
          <span className="kind kind-agent">Agent</span>
        </div>
        {c ? (
          <>
            <p className="summary">{c.summary}</p>
            <div className="readout">
              <div className="tile"><span className="tile-label">Intent</span><span className="tile-value">{nice(c.intent)}</span><span className="tile-sub">{nice(c.product)}</span></div>
              <div className="tile"><span className="tile-label">Urgency</span><span className="tile-value">{pill(urgencyTone(c.urgency), c.urgency)}</span></div>
              <div className="tile"><span className="tile-label">Sentiment</span><span className="tile-value">{pill(sentimentTone(c.sentiment), c.sentiment)}</span></div>
              <div className="tile">
                <span className="tile-label">Confidence</span>
                <span className="tile-value num">{Math.round(c.confidence * 100)}%</span>
                <span className="mini-bar" aria-hidden="true"><span style={{ width: `${c.confidence * 100}%` }} /></span>
              </div>
            </div>
            <div className="risk-row">
              <span className="tile-label">Risk flags</span>
              {c.risk_flags.length ? c.risk_flags.map((r) => pill("risk", r, r)) : <span className="muted">None</span>}
            </div>
          </>
        ) : <Pending label={live ? "Classifying…" : "No classification"} />}
      </section>

      <div className="pair">
        <section className="card">
          <div className="card-head"><h3>Route</h3><span className="kind kind-code">Rules</span></div>
          {route ? (
            <div className="route">
              <span className="route-queue">{route.queue}</span>
              <div className="route-meta">
                {pill(route.priority === "P1" ? "risk" : route.priority === "P2" ? "warn" : "neutral", route.priority)}
                <span>Respond within <b>{route.sla_hours} h</b></span>
              </div>
              <span className="mono muted">rule: {route.rule}</span>
            </div>
          ) : <Pending label={live ? "Routed after the draft…" : "Not routed"} />}
        </section>

        <section className="card">
          <div className="card-head">
            <h3>Knowledge used</h3>
            {findings.relevance !== null && <span className="muted small">coverage {Math.round(findings.relevance * 100)}%</span>}
          </div>
          {sources ? (
            <ul className="sources">
              {sources.slice(0, 5).map((s) => {
                const cited = !!draft?.citations.includes(s.id);
                return (
                  <li key={s.id} className={cited ? "cited" : ""}>
                    <span className="mono src-id">{s.id}</span>
                    <span className="src-title" dir="auto">{s.title}</span>
                    <span className="src-kind">{s.source === "kb" ? "Article" : "Past ticket"}{cited ? ", cited" : ""}</span>
                  </li>
                );
              })}
            </ul>
          ) : <Pending label={live ? "Searching the knowledge base…" : "No knowledge retrieved"} />}
        </section>
      </div>

      <section className="card reply-card">
        {status === "pending_review" && draft && !live ? (
          <Review detail={detail} health={health} onReviewed={onReviewed} />
        ) : (
          <>
            <div className="card-head">
              <h3>{status === "auto_sent" ? "Reply sent automatically" : status === "resolved" ? "Reply sent after review" : status === "rejected" ? "Draft rejected" : "Draft reply"}</h3>
              <span className="kind kind-agent">Agent</span>
            </div>
            {draft ? (
              <>
                <div className="draft" dir="auto">{detail.ticket.final_reply && !live ? detail.ticket.final_reply : draft.reply}</div>
                <Citations ids={draft.citations} />
              </>
            ) : <Pending label={live ? "Drafting a cited reply…" : "No draft"} />}
          </>
        )}
      </section>
    </div>
  );
}

function OutcomeBanner({ gate, status, threshold, failed }: {
  gate: Findings["gate"]; status: Status; threshold: number; failed: boolean;
}) {
  if (failed) {
    return <section className="outcome outcome-risk"><h3>Triage failed</h3><p>See the last step in the agent trace for the error.</p></section>;
  }
  if (!gate) {
    return (
      <section className="outcome outcome-agent">
        <h3>The agent is working on this ticket</h3>
        <p>Findings appear below as each step finishes.</p>
      </section>
    );
  }
  const auto = gate.decision === "auto";
  const title =
    status === "resolved" ? "Reviewed and sent"
    : status === "rejected" ? "Draft rejected by the reviewer"
    : auto ? "Sent automatically" : "Needs your review";
  const tone = status === "rejected" ? "risk" : auto || status === "resolved" ? "ok" : "warn";
  return (
    <section className={`outcome outcome-${tone}`}>
      <div className="outcome-top">
        <h3>{title}</h3>
        <span className="mono">score {gate.score.toFixed(2)} / threshold {threshold.toFixed(2)}</span>
      </div>
      <div className="meter" role="img" aria-label={`Gate score ${gate.score.toFixed(2)} against threshold ${threshold.toFixed(2)}`}>
        <span style={{ width: `${Math.min(100, gate.score * 100)}%` }} />
        <i style={{ left: `${threshold * 100}%` }} />
      </div>
      <ul className="reason-chips">
        {gate.reasons.map((r) => <li key={r}>{r}</li>)}
      </ul>
    </section>
  );
}

function Citations({ ids }: { ids: string[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const [chunk, setChunk] = useState<Chunk | null>(null);
  useEffect(() => {
    setChunk(null);
    if (open) api.chunk(open).then(setChunk).catch(() => setChunk(null));
  }, [open]);
  if (!ids.length) return <p className="muted small">No sources cited.</p>;
  return (
    <>
      <div className="citations" aria-label="Sources cited">
        <span className="muted small">Sources</span>
        {ids.map((id) => (
          <button key={id} className="cite" aria-expanded={open === id} onClick={() => setOpen(open === id ? null : id)}>{id}</button>
        ))}
      </div>
      {open && (
        <div className="passage" dir="auto">
          {chunk ? <><b>{chunk.title}</b>{"\n"}{chunk.text}</> : "Loading source…"}
        </div>
      )}
    </>
  );
}

function Review({ detail, health, onReviewed }: { detail: TicketDetail; health: Health | null; onReviewed: (d: TicketDetail) => void }) {
  const s = detail.state!;
  const original = s.draft!.reply;
  const [reply, setReply] = useState(original);
  const [queue, setQueue] = useState(s.route?.queue ?? "");
  const [reviewer, setReviewer] = useState("Supervisor");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const edited = reply.trim() !== original.trim();
  const queues = health?.queues ?? (s.route ? [s.route.queue] : []);

  const submit = async (action: "approve" | "reject") => {
    setBusy(true);
    setError("");
    try {
      onReviewed(await api.review(detail.ticket.id, { action, reply, queue, reviewer }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="review">
      <div className="card-head">
        <h3>Review the draft</h3>
        {edited ? pill("agent", "edited") : <span className="kind kind-agent">Agent draft</span>}
      </div>
      <textarea value={reply} onChange={(e) => setReply(e.target.value)} dir="auto" aria-label="Reply to the customer" />
      <Citations ids={s.draft!.citations} />
      <div className="review-fields">
        <label>Queue
          <select value={queue} onChange={(e) => setQueue(e.target.value)}>
            {queues.map((q) => <option key={q}>{q}</option>)}
          </select>
        </label>
        <label>Reviewer
          <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button className="btn btn-primary" disabled={busy || !reply.trim()} onClick={() => submit("approve")}>
          {edited ? "Send edited reply" : "Approve and send"}
        </button>
        <button className="btn btn-danger" disabled={busy} onClick={() => submit("reject")}>Reject draft</button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ right: trace */

function TracePanel({ events, live }: { events: TraceEvent[]; live: boolean }) {
  const steps = STEPS.map((s) => {
    const mine = events.filter((e) => (s.key === "outcome" ? OUTCOME_STEPS.has(e.step) : e.step === s.key));
    const done = [...mine].reverse().find((e) => e.status === "done" || e.status === "info");
    const started = mine.find((e) => e.status === "started");
    const state = done ? "done" : started ? "running" : "pending";
    const ms = started && done && started.at && done.at ? new Date(done.at).getTime() - new Date(started.at).getTime() : null;
    const detail = s.key === "outcome"
      ? mine.filter((e) => e.status !== "started").map((e) => e.detail).join(" · ")
      : (done ?? started)?.detail;
    return { ...s, state, detail, ms, isError: mine.some((e) => e.step === "error") };
  });
  const stamps = events.map((e) => e.at).filter(Boolean).map((t) => new Date(t).getTime());
  const total = stamps.length > 1 ? (Math.max(...stamps) - Math.min(...stamps)) / 1000 : null;

  return (
    <section className="side-block">
      <div className="card-head">
        <h3>Agent trace</h3>
        <span className="muted small">{live ? "running…" : total !== null ? `${total.toFixed(1)} s total` : "not run yet"}</span>
      </div>
      <ol className="rail">
        {steps.map((s) => (
          <li key={s.key} className="step" data-state={s.state} data-kind={s.kind === "agent" ? "agent" : "code"}>
            <span className="node" aria-hidden="true" />
            <div>
              <div className="step-head">
                <span className="step-name">{s.name}</span>
                <span className={`kind ${s.kind === "agent" ? "kind-agent" : "kind-code"}`}>
                  {s.kind === "agent" ? "Agent" : s.kind === "result" ? "Result" : "Code"}
                </span>
                <span className="visually-hidden">{s.state}</span>
                {s.ms !== null && s.ms >= 50 && <span className="step-time">{(s.ms / 1000).toFixed(1)} s</span>}
              </div>
              {s.detail && <div className={`step-detail ${s.isError ? "error" : ""}`} dir="auto">{s.detail}</div>}
              {s.state === "running" && <div className="step-detail">Working…</div>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Audit({ entries }: { entries: AuditEntry[] }) {
  return (
    <section className="side-block">
      <h3 className="section-title">Audit trail</h3>
      <ul className="audit">
        {entries.map((a, i) => (
          <li key={i}>
            <span className="mono muted">{new Date(a.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
            <span><b>{a.actor}</b> {a.action.replace(":", ": ").replace("_", " ")}{a.detail?.edited ? " (edited the draft)" : ""}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ------------------------------------------------------------------ new ticket */

function Composer({ onCreated }: { onCreated: (t: TicketSummary) => void }) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [customer, setCustomer] = useState("");
  const [channel, setChannel] = useState("email");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onCreated(await api.create({ subject, body, customer: customer || "Customer", channel }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="composer" onSubmit={submit}>
      <label>Subject<input value={subject} onChange={(e) => setSubject(e.target.value)} required dir="auto" /></label>
      <label>Message<textarea rows={4} value={body} onChange={(e) => setBody(e.target.value)} required dir="auto" /></label>
      <div className="row">
        <label>Customer<input value={customer} onChange={(e) => setCustomer(e.target.value)} dir="auto" /></label>
        <label>Channel
          <select value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="email">Email</option><option value="chat">Chat</option><option value="voice">Voice</option>
          </select>
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      <button className="btn btn-primary" disabled={busy}>{busy ? "Creating…" : "Create and triage"}</button>
    </form>
  );
}

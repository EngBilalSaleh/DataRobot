"use client";

import { useEffect, useState } from "react";
import { api, type QueueStats, type Suggestion } from "@/lib/api";

export default function Insights() {
  const [rows, setRows] = useState<QueueStats[]>([]);
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.insights().then((d) => setRows(d.queues)).catch((e) => setError(e.message));
  }, []);

  const max = Math.max(1, ...rows.flatMap((r) => [r.last_24h, r.daily_avg_prev]));

  const suggest = async () => {
    setBusy(true);
    setError("");
    try {
      setSuggestion(await api.suggest());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="insights">
      <div className="insights-head">
        <div>
          <h1>Queue load</h1>
          <p className="muted" style={{ margin: "4px 0 0" }}>Tickets in the last 24 hours against the average day of the previous six.</p>
        </div>
        <button className="btn btn-primary" onClick={suggest} disabled={busy}>
          {busy ? "Analyzing queues…" : "Suggest staffing"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {suggestion && (
        <div className="suggestion" role="status" style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 16 }}>Staffing suggestion <span className="kind kind-agent">Agent</span></h2>
          <p style={{ margin: "6px 0 0" }}>{suggestion.summary}</p>
          {suggestion.moves.length > 0 && (
            <ul className="moves">
              {suggestion.moves.map((m, i) => (
                <li key={i}>
                  Move <b>{m.agents}</b> agent{m.agents > 1 ? "s" : ""} from <b>{m.from_queue}</b> to <b>{m.to_queue}</b>. <span className="muted">{m.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <table className="qtable">
        <thead>
          <tr>
            <th>Queue</th><th>Last 24 h</th><th>Prior daily average</th><th>Change</th><th>Agents</th><th>Tickets per agent</th><th aria-label="Volume bars" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const rising = r.change_pct >= 20;
            return (
              <tr key={r.queue}>
                <td>{r.queue}</td>
                <td>{r.last_24h}</td>
                <td>{r.daily_avg_prev}</td>
                <td>
                  <span className={`pill ${rising ? "pill-warn" : r.change_pct <= -20 ? "pill-ok" : "pill-neutral"}`}>
                    {r.change_pct > 0 ? "+" : ""}{r.change_pct}%{rising ? " rising" : r.change_pct <= -20 ? " quieter" : ""}
                  </span>
                </td>
                <td>{r.agents}</td>
                <td>{(r.last_24h / Math.max(1, r.agents)).toFixed(1)}</td>
                <td>
                  <div className="bars" aria-hidden="true">
                    <div className="bar bar-now" style={{ width: `${(r.last_24h / max) * 100}%` }} />
                    <div className="bar bar-prev" style={{ width: `${(r.daily_avg_prev / max) * 100}%` }} />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="legend"><span className="l-now">Last 24 hours</span><span className="l-prev">Prior daily average</span></div>
    </main>
  );
}

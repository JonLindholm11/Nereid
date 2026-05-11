import { useState, useEffect, useRef, useCallback } from "react";
import "./NereidHosted.css";

const API = "http://localhost:8000";

const HELP_TEXT = [
  { type: "system", text: "nereid hosted terminal — available commands:" },
  { type: "info",   text: "  status               — show all connection statuses" },
  { type: "info",   text: "  review               — show staged changes for active connection" },
  { type: "info",   text: "  approve all          — promote all staged changes" },
  { type: "info",   text: "  approve <table>      — promote a specific table" },
  { type: "info",   text: "  reject all           — discard all staged changes" },
  { type: "info",   text: "  reject <table>       — discard a specific table" },
  { type: "info",   text: "  use <connection>     — switch active connection" },
  { type: "info",   text: "  clear                — clear terminal output" },
  { type: "info",   text: "  help                 — show this message" },
];

export default function NereidHosted() {
  const [connections, setConnections]         = useState([]);
  const [activeConn, setActiveConn]           = useState(null);
  const [syncLog, setSyncLog]                 = useState([]);
  const [cmdInput, setCmdInput]               = useState("");
  const [loading, setLoading]                 = useState(true);
  const [busy, setBusy]                       = useState(false);
  const [reviewData, setReviewData]           = useState({});
  const logRef   = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { bootstrap(); }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [syncLog]);

  // Poll status every 30s
  useEffect(() => {
    const interval = setInterval(pollStatus, 30000);
    return () => clearInterval(interval);
  }, [activeConn]);

  async function bootstrap() {
    setLoading(true);
    try {
      const data = await fetchStatus();
      if (data.connections.length > 0) {
        setActiveConn(data.connections[0].name);
        addLog("system", `nereid v0.1.0 — ${data.connections.length} connection(s) loaded`);
        data.connections.forEach(c => {
          const status = c.has_changes ? "changes staged" : "watching";
          addLog(c.has_changes ? "diff" : "success", `  ${c.name} — ${status}`);
        });
        addLog("system", "type 'help' for available commands");
      } else {
        addLog("error", "no connections found — check nereid.config.json");
      }
    } catch (e) {
      addLog("error", `failed to connect to nereid server: ${e.message}`);
    }
    setLoading(false);
  }

  async function fetchStatus() {
    const res  = await fetch(`${API}/api/status`);
    const data = await res.json();
    setConnections(data.connections || []);
    return data;
  }

  async function pollStatus() {
    try {
      await fetchStatus();
    } catch (_) {}
  }

  function addLog(type, text, isReview = false, reviewPayload = null) {
    const ts = new Date().toLocaleTimeString("en-US", { hour12: false });
    setSyncLog(prev => [...prev, { type, text, ts, isReview, reviewPayload }]);
  }

  function getActiveConnection() {
    return connections.find(c => c.name === activeConn);
  }

  async function fetchReview(connName) {
    const name = connName || activeConn;
    try {
      const res  = await fetch(`${API}/api/review/${encodeURIComponent(name)}`);
      const data = await res.json();
      setReviewData(data.staged || {});
      if (data.has_changes) {
        addLog("system", `staged changes for '${name}':`, true, data.staged);
      } else {
        addLog("info", "no staged changes found");
      }
    } catch (e) {
      addLog("error", `review failed: ${e.message}`);
    }
  }

  async function runAction(action, table = null) {
    if (!activeConn) { addLog("error", "no active connection"); return; }
    setBusy(true);
    try {
      const res  = await fetch(`${API}/api/review/${encodeURIComponent(activeConn)}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, table }),
      });
      const data = await res.json();

      if (data.result === "approved_all") {
        addLog("success", "all staged changes promoted to production");
        addLog("success", "drive files synced to db state");
        setReviewData({});
      } else if (data.result === "rejected_all") {
        addLog("success", "all staged changes discarded");
        addLog("success", "drive files restored to db state");
        setReviewData({});
      } else if (data.result === "approved_table") {
        addLog("success", `'${table}' promoted to production`);
        await fetchReview(activeConn);
      } else if (data.result === "rejected_table") {
        addLog("success", `'${table}' discarded`);
        await fetchReview(activeConn);
      }

      await fetchStatus();
    } catch (e) {
      addLog("error", `action failed: ${e.message}`);
    }
    setBusy(false);
  }

  async function handleCommand(e) {
    if (e.key !== "Enter") return;
    const raw = cmdInput.trim().toLowerCase();
    if (!raw) return;
    setCmdInput("");
    addLog("cmd", `$ ${raw}`);

    if (raw === "help") {
      HELP_TEXT.forEach(l => addLog(l.type, l.text));

    } else if (raw === "clear") {
      setSyncLog([]);

    } else if (raw === "status") {
      setBusy(true);
      try {
        const data = await fetchStatus();
        data.connections.forEach(c => {
          const alive   = c.watcher_alive ? "watching" : "stopped";
          const changes = c.has_changes ? ` — ${c.staged_tables.length} table(s) staged` : " — clean";
          addLog(c.has_changes ? "diff" : "success", `  ${c.name}: ${alive}${changes}`);
        });
      } catch (e) {
        addLog("error", `status failed: ${e.message}`);
      }
      setBusy(false);

    } else if (raw === "review") {
      await fetchReview(activeConn);

    } else if (raw === "approve all") {
      await runAction("approve_all");

    } else if (raw === "reject all") {
      await runAction("reject_all");

    } else if (raw.startsWith("approve ")) {
      const table = raw.replace("approve ", "").trim();
      await runAction("approve_table", table);

    } else if (raw.startsWith("reject ")) {
      const table = raw.replace("reject ", "").trim();
      await runAction("reject_table", table);

    } else if (raw.startsWith("use ")) {
      const name = raw.replace("use ", "").trim();
      const match = connections.find(c => c.name.toLowerCase() === name);
      if (!match) {
        addLog("error", `connection '${name}' not found`);
        addLog("info", `available: ${connections.map(c => c.name).join(", ")}`);
      } else {
        setActiveConn(match.name);
        setReviewData({});
        addLog("system", `switched to '${match.name}'`);
      }

    } else {
      addLog("error", `unknown command '${raw}' — type 'help' for available commands`);
    }
  }

  const logIcon = type => {
    if (type === "success") return "✓";
    if (type === "error")   return "✗";
    if (type === "diff")    return "~";
    if (type === "cmd")     return "›";
    return "·";
  };

  const activeConnection = getActiveConnection();
  const hasChanges = activeConnection?.has_changes;

  return (
    <div className="hosted-root">

      {/* Header */}
      <div className="hosted-header">
        <div className="header-brand">
          <div className="brand-mark">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <rect x="1" y="1" width="4" height="4" fill="#2a7a4f"/>
              <rect x="7" y="1" width="4" height="4" fill="#2a7a4f" opacity="0.6"/>
              <rect x="1" y="7" width="4" height="4" fill="#2a7a4f" opacity="0.6"/>
              <rect x="7" y="7" width="4" height="4" fill="#2a7a4f" opacity="0.3"/>
            </svg>
          </div>
          <span className="brand-name">nereid</span>
          <span className="brand-version">v0.1.0</span>
        </div>
        <div className="header-right">
          <div className="watcher-indicator">
            <div className={`pulse-dot ${loading ? "loading" : activeConnection?.watcher_alive === false ? "dead" : ""}`} />
            {loading ? "connecting..." : activeConnection?.watcher_alive === false ? "watcher stopped" : "watching"}
          </div>
        </div>
      </div>

      {/* Connection tabs */}
      {connections.length > 1 && (
        <div className="connection-tabs">
          {connections.map(conn => (
            <button
              key={conn.name}
              className={`conn-tab${activeConn === conn.name ? " active" : ""}${conn.has_changes ? " has-changes" : ""}`}
              onClick={() => { setActiveConn(conn.name); setReviewData({}); }}
            >
              <div className="conn-tab-dot" />
              {conn.name}
            </button>
          ))}
        </div>
      )}

      <div className="hosted-main" onClick={() => inputRef.current?.focus()}>

        {/* Status bar */}
        <div className="status-bar">
          <div className="status-bar-left">
            <div className={`status-pill ${loading ? "loading" : hasChanges ? "changes" : "clean"}`}>
              <span>{loading ? "···" : hasChanges ? "staged" : "clean"}</span>
            </div>
            {activeConn && (
              <span style={{ color: "#3a3a3a", fontSize: 11 }}>{activeConn}</span>
            )}
          </div>
          <div className="pipeline-display">
            <span className="step active">watch</span>
            <span className="arrow">→</span>
            <span className={`step ${hasChanges ? "active" : ""}`}>stage</span>
            <span className="arrow">→</span>
            <span className="step">promote</span>
          </div>
        </div>

        {/* Terminal output */}
        <div className="terminal-output" ref={logRef}>
          {syncLog.length === 0 && !loading && (
            <span className="log-empty">waiting for changes...</span>
          )}
          {syncLog.map((entry, i) => (
            <div key={i}>
              <div className={`log-line ${entry.type}`}>
                <span className="log-ts">{entry.ts}</span>
                <span className="log-icon">{logIcon(entry.type)}</span>
                <span className="log-text">{entry.text}</span>
              </div>
              {entry.isReview && entry.reviewPayload && Object.entries(entry.reviewPayload).map(([table, rows]) => (
                <div key={table} className="review-block">
                  <div className="review-block-header">
                    <span className="review-table-name">{table}</span>
                    <div className="review-actions">
                      <button className="btn-approve" onClick={() => runAction("approve_table", table)}>approve</button>
                      <button className="btn-reject"  onClick={() => runAction("reject_table", table)}>reject</button>
                    </div>
                  </div>
                  {rows.length > 0 && (
                    <table className="review-mini-table">
                      <thead>
                        <tr>{Object.keys(rows[0]).map(k => <th key={k}>{k}</th>)}</tr>
                      </thead>
                      <tbody>
                        {rows.slice(0, 5).map((r, ri) => (
                          <tr key={ri}>{Object.values(r).map((v, vi) => <td key={vi}>{String(v)}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {rows.length > 5 && (
                    <div className="review-more">+{rows.length - 5} more rows</div>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>

        {/* Terminal input */}
        <div className="terminal-input-area">
          <div className="terminal-input-row">
            <span className="terminal-prompt">nereid {activeConn ? `[${activeConn}]` : ""} $</span>
            <input
              ref={inputRef}
              className="terminal-input"
              value={cmdInput}
              onChange={e => setCmdInput(e.target.value)}
              onKeyDown={handleCommand}
              placeholder={busy ? "working..." : "type 'help' for commands..."}
              disabled={busy}
              spellCheck={false}
              autoComplete="off"
            />
          </div>
          <div className="terminal-hint">
            review · approve all · reject &lt;table&gt; · use &lt;connection&gt; · help
          </div>
        </div>
      </div>
    </div>
  );
}
import { useState, useEffect, useRef } from "react";
import "./NereidDemo.css";

const API = "http://localhost:8000";

const COLUMNS = {
  customers: ["id", "name", "email", "phone", "status"],
  products: ["id", "name", "sku", "price", "stock"],
  orders: ["id", "customer_id", "product", "quantity", "total_price", "status"],
};

const COL_WIDTHS = {
  id: 60, name: 180, email: 200, phone: 120, status: 110,
  sku: 100, price: 90, stock: 80,
  customer_id: 100, product: 180, quantity: 80, total_price: 110,
};

const STATUS_OPTIONS = ["active", "inactive", "pending", "completed", "shipped"];

const STATUS_TEXT = {
  active: "#137333", inactive: "#c5221f",
  completed: "#137333", pending: "#b06000", shipped: "#1a56db",
};

const HELP_TEXT = [
  { type: "system", text: "available commands:" },
  { type: "info",   text: "  review              — show staged changes" },
  { type: "info",   text: "  approve all         — promote all staged changes" },
  { type: "info",   text: "  approve <table>     — promote a specific table" },
  { type: "info",   text: "  reject all          — discard all staged changes" },
  { type: "info",   text: "  reject <table>      — discard a specific table" },
  { type: "info",   text: "  clear               — clear terminal output" },
  { type: "info",   text: "  help                — show this message" },
];

export default function NereidDemo() {
  const [sessionId, setSessionId]   = useState(null);
  const [activeTab, setActiveTab]   = useState("customers");
  const [editData, setEditData]     = useState({ customers: [], products: [], orders: [] });
  const [syncLog, setSyncLog]       = useState([]);
  const [status, setStatus]         = useState("idle");
  const [timeLeft, setTimeLeft]     = useState(60 * 60);
  const [loading, setLoading]       = useState(true);
  const [cmdInput, setCmdInput]     = useState("");
  const [reviewData, setReviewData] = useState({});
  const timerRef   = useRef(null);
  const logRef     = useRef(null);
  const inputRef   = useRef(null);
  const sessionRef = useRef(null);

  useEffect(() => {
    initSession();
    return () => clearInterval(timerRef.current);
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [syncLog]);

  async function initSession() {
    setLoading(true);
    try {
      const res  = await fetch(`${API}/demo/session`, { method: "POST" });
      const data = await res.json();
      setSessionId(data.session_id);
      sessionRef.current = data.session_id;
      await loadData(data.session_id);
      startTimer();
      addLog("system", "nereid demo session started");
      addLog("system", "edit cells and click save to stage changes");
      addLog("system", "type 'help' to see available commands");
    } catch (e) {
      addLog("error", "failed to connect to nereid server");
    }
    setLoading(false);
  }

  function startTimer() {
    timerRef.current = setInterval(() => {
      setTimeLeft(t => {
        if (t <= 1) {
          clearInterval(timerRef.current);
          addLog("error", "session expired — reload to start a new demo");
          return 0;
        }
        return t - 1;
      });
    }, 1000);
  }

  async function loadData(sid) {
    const id  = sid || sessionRef.current;
    const res  = await fetch(`${API}/demo/session/${id}`);
    const data = await res.json();
    setEditData({
      customers: data.customers.map(r => ({ ...r })),
      products:  data.products.map(r => ({ ...r })),
      orders:    data.orders.map(r => ({ ...r })),
    });
  }

  function addLog(type, text, isReview = false, reviewPayload = null) {
    const ts = new Date().toLocaleTimeString("en-US", { hour12: false });
    setSyncLog(prev => [...prev, { type, text, ts, isReview, reviewPayload }]);
  }

  function handleCellEdit(table, rowIdx, col, value) {
    setEditData(prev => ({
      ...prev,
      [table]: prev[table].map((row, i) => i === rowIdx ? { ...row, [col]: value } : row),
    }));
  }

  function addRow() {
    const cols  = COLUMNS[activeTab];
    const empty = Object.fromEntries(cols.map(c => [c, ""]));
    setEditData(prev => ({ ...prev, [activeTab]: [...prev[activeTab], empty] }));
  }

  function deleteRow(idx) {
    setEditData(prev => ({ ...prev, [activeTab]: prev[activeTab].filter((_, i) => i !== idx) }));
  }

  async function handleSave() {
    setStatus("busy");
    addLog("cmd", "$ save");
    try {
      const res  = await fetch(`${API}/demo/save/${sessionRef.current}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editData),
      });
      const data = await res.json();
      const s    = data.summary;
      let hasChanges = false;

      Object.entries(s).forEach(([table, summary]) => {
        if (summary !== "no changes") {
          addLog("diff", `${table}: ${summary}`);
          hasChanges = true;
        }
      });

      if (!hasChanges) {
        addLog("info", "no changes detected");
        setStatus("idle");
      } else {
        addLog("success", "changes staged — run 'review' to inspect");
        setStatus("staged");
        await fetchReview();
      }
    } catch (e) {
      addLog("error", `save failed: ${e.message}`);
      setStatus("idle");
    }
  }

  async function fetchReview() {
    try {
      const res  = await fetch(`${API}/demo/review/${sessionRef.current}`);
      const data = await res.json();
      setReviewData(data.staged || {});
      if (data.has_changes) {
        addLog("system", "staged changes ready for review:", true, data.staged);
      } else {
        addLog("info", "no staged changes found");
      }
    } catch (e) {
      addLog("error", `review fetch failed: ${e.message}`);
    }
  }

  async function runAction(action, table = null) {
    setStatus("busy");
    try {
      const res  = await fetch(`${API}/demo/review/${sessionRef.current}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, table }),
      });
      const data = await res.json();

      if (data.result === "approved_all") {
        addLog("success", "all staged changes promoted to production");
        setReviewData({});
        await loadData();
        setStatus("idle");
      } else if (data.result === "rejected_all") {
        addLog("success", "all staged changes discarded");
        setReviewData({});
        setStatus("idle");
      } else if (data.result === "approved_table") {
        addLog("success", `'${table}' promoted to production`);
        await loadData();
        await fetchReview();
        setStatus("idle");
      } else if (data.result === "rejected_table") {
        addLog("success", `'${table}' discarded`);
        await fetchReview();
        setStatus("idle");
      }
    } catch (e) {
      addLog("error", `action failed: ${e.message}`);
      setStatus("idle");
    }
  }

  async function handleReset() {
    setStatus("busy");
    addLog("system", "hard reset triggered...");
    try {
      await fetch(`${API}/demo/reset/${sessionRef.current}`, { method: "POST" });
      await loadData();
      setSyncLog([]);
      setReviewData({});
      setStatus("idle");
      addLog("system", "session reset — seed data restored");
      addLog("system", "type 'help' to see available commands");
    } catch (e) {
      addLog("error", `reset failed: ${e.message}`);
      setStatus("idle");
    }
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
    } else if (raw === "review") {
      await fetchReview();
    } else if (raw === "approve all") {
      await runAction("approve_all");
    } else if (raw === "reject all") {
      await runAction("reject_all");
    } else if (raw.startsWith("approve ")) {
      const table = raw.replace("approve ", "").trim();
      if (!["customers", "products", "orders"].includes(table)) {
        addLog("error", `unknown table '${table}' — valid tables: customers, products, orders`);
      } else {
        await runAction("approve_table", table);
      }
    } else if (raw.startsWith("reject ")) {
      const table = raw.replace("reject ", "").trim();
      if (!["customers", "products", "orders"].includes(table)) {
        addLog("error", `unknown table '${table}' — valid tables: customers, products, orders`);
      } else {
        await runAction("reject_table", table);
      }
    } else {
      addLog("error", `unknown command '${raw}' — type 'help' for available commands`);
    }
  }

  const fmt = s => {
    const m   = Math.floor(s / 60).toString().padStart(2, "0");
    const sec = (s % 60).toString().padStart(2, "0");
    return `${m}:${sec}`;
  };

  const timerClass = timeLeft < 300 ? "timer warning" : timeLeft < 600 ? "timer caution" : "timer normal";

  const logIcon = type => {
    if (type === "success") return "✓";
    if (type === "error")   return "✗";
    if (type === "diff")    return "~";
    return "·";
  };

  if (loading) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", fontFamily: "monospace", color: "#5f6368", fontSize: 14 }}>
      starting nereid demo session...
    </div>
  );

  const cols = COLUMNS[activeTab];
  const rows = editData[activeTab];

  return (
    <div className="demo-root">

      {/* Top bar */}
      <div className="topbar">
        <div className="topbar-left">
          <div className="topbar-logo">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <rect x="2" y="2" width="5" height="5" fill="white" opacity="0.9"/>
              <rect x="9" y="2" width="5" height="5" fill="white" opacity="0.9"/>
              <rect x="2" y="9" width="5" height="5" fill="white" opacity="0.9"/>
              <rect x="9" y="9" width="5" height="5" fill="white" opacity="0.7"/>
            </svg>
          </div>
          <span className="topbar-title">Nereid Demo</span>
          <span className="topbar-badge">sandbox</span>
        </div>
        <div className="topbar-right">
          <div className={timerClass}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.2"/>
              <path d="M7 4v3.5l2 1.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
            </svg>
            {fmt(timeLeft)} remaining
          </div>
          <button className="btn-reset" onClick={handleReset}>Reset</button>
        </div>
      </div>

      {/* Sheets toolbar */}
      <div className="sheets-toolbar">
        <button className="btn-add-row" onClick={addRow}>
          <span style={{ fontSize: 16, lineHeight: 1 }}>+</span> Add row
        </button>
        <button className="btn-save" onClick={handleSave} disabled={status === "busy"}>
          {status === "busy" ? "Working..." : "Save"}
        </button>
      </div>

      <div className="demo-main">

        {/* Spreadsheet 60% */}
        <div className="spreadsheet-area">
          <div className="table-scroll">
            <table className="sheet-table">
              <colgroup>
                <col style={{ width: 36 }} />
                {cols.map(c => <col key={c} style={{ width: COL_WIDTHS[c] || 120 }} />)}
                <col style={{ width: 36 }} />
              </colgroup>
              <thead>
                <tr>
                  <th className="row-num"></th>
                  {cols.map(col => <th key={col}>{col}</th>)}
                  <th className="row-del"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, ri) => (
                  <tr key={ri}>
                    <td className="row-num">{ri + 1}</td>
                    {cols.map(col => (
                      <td key={col}>
                        {col === "status" ? (
                          <select
                            className="cell-select"
                            value={row[col] || ""}
                            onChange={e => handleCellEdit(activeTab, ri, col, e.target.value)}
                            style={{ color: STATUS_TEXT[row[col]] || "#202124" }}
                          >
                            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
                          </select>
                        ) : (
                          <input
                            className="cell-input"
                            value={row[col] !== undefined ? row[col] : ""}
                            onChange={e => handleCellEdit(activeTab, ri, col, e.target.value)}
                          />
                        )}
                      </td>
                    ))}
                    <td className="row-del">
                      <button className="btn-delete-row" onClick={() => deleteRow(ri)}>×</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="sheet-tabs">
            {["customers", "products", "orders"].map(tab => (
              <button
                key={tab}
                className={`sheet-tab${activeTab === tab ? " active" : ""}`}
                onClick={() => setActiveTab(tab)}
              >
                {tab}
              </button>
            ))}
          </div>
        </div>

        {/* Terminal panel 40% */}
        <div className="terminal-panel" onClick={() => inputRef.current?.focus()}>
          <div className="terminal-header">
            <div className="terminal-header-left">
              <div className={`status-dot ${status === "idle" ? "idle" : status === "staged" ? "staged" : "busy"}`} />
              <span className="terminal-label">nereid sync terminal</span>
            </div>
            <div className="pipeline">
              <span className="active">watch</span>
              <span>→</span>
              <span className={status === "staged" ? "active" : ""}>stage</span>
              <span>→</span>
              <span className={status === "idle" && Object.keys(reviewData).length === 0 ? "active" : ""}>promote</span>
            </div>
          </div>

          <div className="terminal-output" ref={logRef}>
            {syncLog.length === 0 && (
              <span className="log-empty">waiting for changes...</span>
            )}
            {syncLog.map((entry, i) => (
              <div key={i}>
                <div className={`log-line ${entry.type}`}>
                  <span className="log-ts">{entry.ts}</span>
                  <span className="log-icon">{logIcon(entry.type)}</span>
                  <span className="log-text">{entry.text}</span>
                </div>
                {entry.isReview && entry.reviewPayload && Object.entries(entry.reviewPayload).map(([table, tableRows]) => (
                  <div key={table} className="review-block">
                    <div className="review-block-header">
                      <span className="review-table-name">{table}</span>
                      <div className="review-block-actions">
                        <button className="btn-approve-table" onClick={() => runAction("approve_table", table)}>approve</button>
                        <button className="btn-reject-table"  onClick={() => runAction("reject_table", table)}>reject</button>
                      </div>
                    </div>
                    {tableRows.length > 0 && (
                      <table className="review-mini-table">
                        <thead>
                          <tr>{Object.keys(tableRows[0]).map(k => <th key={k}>{k}</th>)}</tr>
                        </thead>
                        <tbody>
                          {tableRows.slice(0, 5).map((r, ri) => (
                            <tr key={ri}>{Object.values(r).map((v, vi) => <td key={vi}>{String(v)}</td>)}</tr>
                          ))}
                          {tableRows.length > 5 && (
                            <tr>
                              <td colSpan={Object.keys(tableRows[0]).length} style={{ color: "#5f6368" }}>
                                +{tableRows.length - 5} more rows
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    )}
                  </div>
                ))}
              </div>
            ))}
          </div>

          <div className="terminal-input-row">
            <span className="terminal-prompt">nereid $</span>
            <input
              ref={inputRef}
              className="terminal-input"
              value={cmdInput}
              onChange={e => setCmdInput(e.target.value)}
              onKeyDown={handleCommand}
              placeholder="type 'help' for commands..."
              spellCheck={false}
              autoComplete="off"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
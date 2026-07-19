"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import ModeTabs from "./ModeTabs";
import DatasetManager from "./DatasetManager";
import DataPreview from "./DataPreview";
import SuggestedQuestions from "./SuggestedQuestions";
import styles from "../app/page.module.css";
import { askAnalyst } from "../utils/datasets";

// Plotly touches `window`, so it must not be server-rendered.
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdown(text) {
  let out = escapeHtml(text);
  out = out.replace(
    /```([\s\S]*?)```/g,
    (_, code) => `<pre><code>${code}</code></pre>`,
  );
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\n/g, "<br/>");
  return out;
}

/** Turn raw backend/model errors into something actionable for the user. */
function formatBackendError(msg) {
  const text = String(msg);
  if (/RESOURCE_EXHAUSTED|429|quota/i.test(text)) {
    return (
      "Gemini API quota exceeded. The analyst makes several model calls per " +
      "question, which exhausts the free tier quickly — wait for the quota to " +
      "reset or enable billing on your Google AI key."
    );
  }
  if (/PERMISSION_DENIED|suspended|API key not valid/i.test(text)) {
    return "The Google API key was rejected (invalid or suspended). Check GOOGLE_API_KEY in the backend .env.";
  }
  if (/NOT_FOUND.*model|model.*not found/i.test(text)) {
    return "The configured Gemini model isn't available to this API key. Update GEN_MODEL in the backend .env.";
  }
  return text;
}

const TOOL_LABELS = {
  list_tables: "🗂️ Listed tables",
  get_schema: "🔎 Inspected schema",
  run_sql: "🧮 Ran SQL",
  run_python: "🐍 Ran Python",
};

/** One step of the agent's tool-call trace, expandable to show args/results. */
function TraceStep({ step }) {
  const [open, setOpen] = useState(false);
  const label = TOOL_LABELS[step.tool] || `🔧 ${step.tool}`;
  const detail = step.args?.query || step.args?.code || step.args?.table || "";

  return (
    <div className={styles.traceStep}>
      <button className={styles.traceHeader} onClick={() => setOpen((v) => !v)}>
        <span>{open ? "▾" : "▸"}</span>
        <span className={styles.traceLabel}>{label}</span>
        {detail && !open && (
          <span className={styles.tracePreview}>
            {detail.slice(0, 60)}
            {detail.length > 60 ? "…" : ""}
          </span>
        )}
      </button>
      {open && (
        <div className={styles.traceBody}>
          {detail && <pre className={styles.traceCode}>{detail}</pre>}
          <pre className={styles.traceResult}>
            {JSON.stringify(step.result_preview, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function AnalystMessage({ m }) {
  if (m.role === "system") {
    return <div className={styles.systemMsg}>{m.text}</div>;
  }
  if (m.role === "user") {
    return (
      <div className={styles.bubbleUser}>
        <div className={styles.userHeader}>You</div>
        <div dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }} />
      </div>
    );
  }

  let figure = null;
  if (m.figJson) {
    try {
      figure = JSON.parse(m.figJson);
    } catch {
      figure = null;
    }
  }

  return (
    <div className={styles.bubbleAssistant}>
      <div className={styles.assistantHeader}>Analyst</div>
      <div dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text || "") }} />

      {figure && (
        <div className={styles.chartWrap}>
          <Plot
            data={figure.data}
            layout={{
              ...figure.layout,
              autosize: true,
              margin: { l: 50, r: 20, t: 40, b: 50 },
              paper_bgcolor: "transparent",
              plot_bgcolor: "transparent",
            }}
            style={{ width: "100%", height: "380px" }}
            useResizeHandler
            config={{ displayModeBar: false, responsive: true }}
          />
        </div>
      )}

      {m.trace?.length > 0 && (
        <details className={styles.traceWrap}>
          <summary className={styles.traceSummary}>
            How I got this ({m.trace.length} step
            {m.trace.length === 1 ? "" : "s"})
          </summary>
          {m.trace.map((step, i) => (
            <TraceStep key={i} step={step} />
          ))}
        </details>
      )}
    </div>
  );
}

export default function DataAnalyst({
  apiBase,
  theme,
  setTheme,
  sidebarOpen,
  setSidebarOpen,
  mode,
  setMode,
}) {
  const [dataset, setDataset] = useState(null); // {id, name, ...}
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState([]);
  const chatRef = useRef(null);
  const abortRef = useRef(null);

  // Remember the selected dataset across reloads.
  useEffect(() => {
    if (dataset?.id) localStorage.setItem("analyst_dataset_id", dataset.id);
  }, [dataset?.id]);

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages, busy]);

  const pushSystem = useCallback(
    (text) => setMessages((m) => [...m, { role: "system", text }]),
    [],
  );

  async function ask(e) {
    e?.preventDefault?.();
    if (busy) return;
    const q = question.trim();
    if (!q) return;
    if (!dataset) {
      pushSystem("Select or upload a dataset first.");
      return;
    }

    setMessages((m) => [...m, { role: "user", text: q }]);
    setQuestion("");
    setBusy(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const data = await askAnalyst(apiBase, dataset.id, q, controller.signal);

      // The agent can fail mid-run (e.g. model quota) and still return HTTP 200
      // with a structured error — surface it instead of showing an empty answer.
      if (data.error) {
        if (data.trace?.length) {
          setMessages((m) => [
            ...m,
            {
              role: "assistant",
              text: "I ran into an error before I could finish. Here's how far I got:",
              trace: data.trace,
              figJson: data.fig_json || null,
            },
          ]);
        }
        pushSystem(`⚠️ ${formatBackendError(data.error)}`);
        return;
      }

      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: data.answer || "(no answer)",
          trace: data.trace || [],
          figJson: data.fig_json || null,
          truncated: data.truncated,
        },
      ]);
      if (data.truncated) {
        pushSystem(
          "⚠️ The agent hit its tool-call limit before finishing. Try a narrower question.",
        );
      }
    } catch (err) {
      if (err.name === "AbortError") {
        pushSystem("Analysis cancelled.");
      } else {
        pushSystem(`⚠️ ${err.message || err}`);
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  function cancel() {
    abortRef.current?.abort();
  }

  function ThemeToggle() {
    return (
      <button
        className={styles.themeToggle}
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        aria-label="Toggle theme"
      >
        {theme === "dark" ? (
          <span style={{ fontSize: 20, color: "#fff" }}>🌙</span>
        ) : (
          <span style={{ fontSize: 20, color: "#222" }}>☀️</span>
        )}
      </button>
    );
  }

  return (
    <>
      <aside
        className={`${styles.sidebar} ${!sidebarOpen ? styles.sidebarClosed : ""}`}
      >
        <div
          style={{ padding: 20, borderBottom: "1px solid var(--sidebar-border)" }}
        >
          <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 12 }}>
            Data Analyst
          </h2>
          <button
            className={styles.newChatBtn}
            onClick={() => setMessages([])}
            disabled={busy}
          >
            + New Analysis
          </button>
          <DatasetManager
            apiBase={apiBase}
            dataset={dataset}
            setDataset={setDataset}
            onSystemMessage={pushSystem}
          />
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
          {dataset?.tables?.length > 0 && (
            <>
              <div className={styles.logsTitle}>
                <b>Schema</b>
              </div>
              {dataset.tables.map((t) => {
                const cols = dataset.schema?.[t.name] || t.columns || [];
                return (
                  <div key={t.name} className={styles.schemaTable}>
                    <div className={styles.schemaTableName}>
                      {t.name}
                      {typeof t.row_count === "number" && (
                        <span className={styles.schemaRowCount}>
                          {t.row_count} rows
                        </span>
                      )}
                    </div>
                    <ul className={styles.schemaCols}>
                      {cols.map((c) => (
                        <li key={c.name}>
                          <span className={styles.schemaColName}>{c.name}</span>
                          <span className={styles.schemaColType}>{c.type}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </>
          )}
        </div>
      </aside>

      <main className={styles.main}>
        <div className={styles.header}>
          <button
            className={styles.sandwich}
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label="Toggle sidebar"
          >
            ☰
          </button>
          <ModeTabs mode={mode} setMode={setMode} />
          <div style={{ flex: 1 }} />
          <ThemeToggle />
        </div>

        <div
          ref={chatRef}
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "32px 0 120px 0",
            background: "var(--bg)",
            display: "flex",
            flexDirection: "column",
            justifyContent: "flex-end",
          }}
        >
          <div
            style={{
              maxWidth: 760,
              margin: "0 auto",
              width: "100%",
              padding: "0 24px",
            }}
          >
            {messages.length === 0 && (
              <>
                <div className={styles.emptyMsg}>
                  {dataset
                    ? `Ask a question about “${dataset.name}” — I can write SQL, run Python, and draw charts.`
                    : "Upload a CSV/Excel/PDF/DOCX or connect a database to get started."}
                </div>
                <DataPreview apiBase={apiBase} dataset={dataset} />
                <SuggestedQuestions
                  dataset={dataset}
                  disabled={busy}
                  onPick={(q) => setQuestion(q)}
                />
              </>
            )}
            {messages.map((m, i) => (
              <AnalystMessage key={i} m={m} />
            ))}
            {busy && (
              <div className={styles.typingBubble}>
                <div className={styles.assistantHeader}>Analyst</div>
                <div>Analyzing… (writing and running queries)</div>
                <button className={styles.stopBtn} onClick={cancel}>
                  ⏹ Stop
                </button>
              </div>
            )}
          </div>
        </div>

        <div className={styles.composer}>
          <form className={styles.composerForm} onSubmit={ask}>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={
                dataset
                  ? "e.g. What is total revenue by region? Show a bar chart."
                  : "Select a dataset first…"
              }
              rows={1}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(e);
                }
              }}
              className={styles.textarea}
              disabled={busy || !dataset}
            />
            <button
              className={styles.sendBtn}
              type="submit"
              disabled={busy || !dataset || !question.trim()}
              aria-label="Send"
            >
              ➤
            </button>
          </form>
          <div className={styles.composerHint}>
            The agent inspects the schema, writes SQL/Python, and runs it. Expand
            “How I got this” on any answer to see each step.
          </div>
        </div>
      </main>
    </>
  );
}

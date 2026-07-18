"use client";
import Sidebar from "./Sidebar";
import ModeTabs from "./ModeTabs";
import { useState, useRef, useEffect } from "react";
import styles from "../app/page.module.css";

// Helper: Remove [chunk X] and similar from text
function cleanAssistantText(text) {
  return text
    .replace(/\[chunk \d+\]\([^)]+\)/g, "")
    .replace(/\[chunk \d+\]/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function formatBackendErrorMessage(errorMsg) {
  if (/models\/text-embedding-004/i.test(errorMsg)) {
    return (
      "The backend is using an unsupported embedding model for this API version. " +
      "Update the server to a supported embedding model or API version, then retry."
    );
  }

  return errorMsg;
}

// Helper: Extract and deduplicate citations from backend response
function extractCitations(meta) {
  if (!meta?.citations || !Array.isArray(meta.citations)) return [];
  const seen = new Set();
  return meta.citations
    .map((c) => {
      const label = `[#${c.chunk_index}${c.page ? ` · p. ${c.page}` : ""}]`;
      const file = c.source?.split("/").pop() || "";
      const key = `${c.chunk_index}-${file}`;
      return { ...c, label, file, key };
    })
    .filter((c) => {
      if (seen.has(c.key)) return false;
      seen.add(c.key);
      return true;
    });
}

// Helper: escape raw text so it can't inject HTML/scripts
function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Helper: Markdown rendering (basic, can swap for a lib).
// Escapes first so content from the user or from ingested PDFs (which can
// end up quoted in the assistant's answer) can't inject arbitrary HTML.
function renderMarkdown(text) {
  text = escapeHtml(text);
  text = text.replace(
    /```([\s\S]*?)```/g,
    (_, code) => `<pre><code>${code}</code></pre>`,
  );
  text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
  text = text.replace(/\n/g, "<br/>");
  return text;
}

// Helper: Animate text appearance (simulate typing)
function useTypewriter(fullText, enabled, speed = 35) {
  const [displayed, setDisplayed] = useState("");
  useEffect(() => {
    if (!enabled) {
      setDisplayed(fullText);
      return;
    }
    setDisplayed("");
    if (!fullText) return;
    let i = 0;
    let cancelled = false;
    function tick() {
      if (cancelled) return;
      i++;
      setDisplayed(fullText.slice(0, i));
      if (i < fullText.length) {
        setTimeout(tick, speed);
      }
    }
    tick();
    return () => {
      cancelled = true;
    };
  }, [fullText, enabled, speed]);
  return displayed;
}

export default function DocumentChat({
  apiBase,
  theme,
  setTheme,
  sidebarOpen,
  setSidebarOpen,
  mode,
  setMode,
}) {
  const [apiBaseRaw] = useState(apiBase || "");
  const [collection, setCollection] = useState(""); // default to empty, let CollectionManager handle
  const [attachments, setAttachments] = useState([]); // [{file, id, status, chunks, error}]
  const [uploadBusy, setUploadBusy] = useState(false);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState([]);
  const [logs, setLogs] = useState([]);
  const [topK, setTopK] = useState(8);
  const [simThreshold, setSimThreshold] = useState(0.5);
  const [streamAbort, setStreamAbort] = useState(null);
  const [systemMsg, setSystemMsg] = useState(""); // for system messages/toasts

  const chatRef = useRef(null);

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages, busy]);

  const pushLog = (s) => setLogs((x) => [s, ...x].slice(0, 100));

  // Ingest and ask: always use current collection
  async function ingest() {
    if (attachments.length === 0) return alert("Choose a PDF first");
    if (!collection)
      return alert("Please select or create a collection first.");
    setUploadBusy(true);
    try {
      const fd = new FormData();
      fd.append("collection", collection);
      attachments.forEach((att) => {
        fd.append("files", att.file, att.file.name);
      });
      const res = await fetch(apiBaseRaw + "/ingest", {
        method: "POST",
        body: fd,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || JSON.stringify(data));
      pushLog(`Ingested ${data.source} → ${data.chunks} chunks`);
      setMessages((m) => [
        ...m,
        {
          role: "system",
          text: `Ingested ‘${attachments
            .map((att) => att.file.name)
            .join(", ")}’ → ${data.chunks} chunks.`,
        },
      ]);
      setAttachments([]);
    } catch (e) {
      console.error(e);
      alert(`Ingest failed: ${e.message || e}`);
    } finally {
      setUploadBusy(false);
    }
  }

  async function ask(regenIdx = null, event = null) {
    if (event) event.preventDefault?.();
    if (busy) return;
    if (!collection) {
      alert("Please select or create a collection first.");
      return;
    }
    let apiBase = apiBaseRaw;
    if (!apiBase) {
      apiBase = "http://127.0.0.1:8000";
      console.warn("apiBase was empty, defaulting to", apiBase);
    }

    const q =
      regenIdx === null ? question.trim() : messages[regenIdx - 1]?.text;
    if (!q) return;

    // Log send intent
    console.log(
      "[Send] (SSE) apiBase:",
      apiBase,
      "collection:",
      collection,
      "question:",
      q,
    );

    setBusy(true);

    // Add user message if not regen
    let userIdx = null;
    if (regenIdx === null) {
      setMessages((m) => [...m, { role: "user", text: q }]);
      userIdx = messages.length;
      setQuestion("");
    } else {
      userIdx = regenIdx - 1;
    }

    // Add assistant placeholder (with busy flag)
    let assistantIdx = regenIdx === null ? messages.length + 1 : regenIdx;
    setMessages((m) =>
      regenIdx === null
        ? [...m, { role: "assistant", text: "", meta: {}, busy: true }]
        : m.map((msg, i) =>
            i === regenIdx ? { ...msg, text: "", meta: {}, busy: true } : msg,
          ),
    );

    // Streaming logic
    const controller = new AbortController();
    setStreamAbort(controller);

    const url = apiBase + "/query_stream";
    const body = {
      collection,
      question: q,
      top_k: topK,
      sim_threshold: simThreshold,
      suggest_search: true,
    };
    console.log("[Send] POST (SSE)", url, body);

    try {
      const res = await fetch(url, {
        method: "POST",
        mode: "cors",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      console.log("[Send] Response status:", res.status, res.statusText);

      if (!res.ok) {
        const errText = await res.text();
        console.error("[Send] HTTP error response:", res.status, errText);
        setMessages((msgs) => [
          ...msgs,
          {
            role: "system",
            text: `⚠️ Server error: HTTP ${res.status} - ${errText || res.statusText}`,
          },
        ]);
        setBusy(false);
        setStreamAbort(null);
        return;
      }

      // Fallback: If not SSE, try to read as JSON and render as normal
      const contentType = res.headers.get("content-type") || "";
      if (!contentType.includes("text/event-stream")) {
        console.warn(
          "[SSE] Response is not text/event-stream, falling back to JSON.",
        );
        const data = await res.json().catch(() => ({}));
        console.log("[SSE] JSON fallback data:", data);
        setMessages((msgs) =>
          msgs.map((msg, i) =>
            i === (regenIdx === null ? msgs.length - 1 : regenIdx)
              ? {
                  ...msg,
                  text: data.answer || "(no answer)",
                  meta: data,
                  busy: false,
                }
              : msg,
          ),
        );
        setBusy(false);
        setStreamAbort(null);
        return;
      }

      // SSE streaming
      const reader = res.body.getReader();
      let buffer = "";
      let done = false;
      let currentMsg = { role: "assistant", text: "", meta: {}, busy: true };

      function updateAssistantMsg(upd) {
        setMessages((msgs) =>
          msgs.map((msg, i) =>
            i === (regenIdx === null ? msgs.length - 1 : regenIdx)
              ? { ...msg, ...upd }
              : msg,
          ),
        );
      }

      let lastEvent = null;
      while (!done) {
        const { value, done: streamDone } = await reader.read();
        if (streamDone) break;
        buffer += new TextDecoder().decode(value);

        // Parse lines
        let lines = buffer.split("\n");
        buffer = lines.pop(); // last line may be incomplete

        for (let line of lines) {
          line = line.trim();
          if (!line) continue;
          if (line.startsWith("event:")) {
            lastEvent = line.slice(6).trim();
            continue;
          }
          if (line.startsWith("data:")) {
            let dataStr = line.slice(5).trim();
            let event = lastEvent;
            // Try to parse as JSON
            let payload;
            try {
              payload = JSON.parse(dataStr);
            } catch {
              payload = { text: dataStr };
            }
            // Logging
            console.log("[SSE]", event, payload);

            // Handle events
            if (event === "token") {
              // Append token to assistant message
              currentMsg.text += payload.text || "";
              updateAssistantMsg({ text: currentMsg.text, busy: true });
              // Scroll to bottom
              setTimeout(() => {
                if (chatRef.current)
                  chatRef.current.scrollTop = chatRef.current.scrollHeight;
              }, 0);
            } else if (event === "citations") {
              currentMsg.meta = currentMsg.meta || {};
              currentMsg.meta.citations = payload.citations || [];
              updateAssistantMsg({ meta: currentMsg.meta, busy: true });
            } else if (event === "not_found") {
              currentMsg.text = payload.answer || "";
              currentMsg.meta = { suggested_search: payload.suggested_search };
              updateAssistantMsg({
                text: currentMsg.text,
                meta: currentMsg.meta,
                busy: false,
              });
              done = true;
              break;
            } else if (event === "error") {
              const errorMsg =
                payload.message || payload.error || "Unknown error";
              const friendlyError = formatBackendErrorMessage(errorMsg);
              console.warn("[SSE] Backend error event:", friendlyError);
              currentMsg.text = friendlyError;
              updateAssistantMsg({ text: currentMsg.text, busy: false });
              setMessages((msgs) => [
                ...msgs,
                {
                  role: "system",
                  text: "⚠️ Error: " + friendlyError,
                },
              ]);
              done = true;
              break;
            } else if (event === "done") {
              updateAssistantMsg({ busy: false });
              done = true;
              break;
            }
          }
        }
      }
      // Finalize
      setBusy(false);
      setStreamAbort(null);
      updateAssistantMsg({ busy: false });
      console.log("[SSE] Stream done.");
    } catch (e) {
      console.error("[SSE] Error", e);
      setMessages((msgs) => [
        ...msgs,
        {
          role: "system",
          text: "⚠️ Network error or aborted.",
        },
      ]);
      setBusy(false);
      setStreamAbort(null);
    }
  }

  function cancelStream() {
    if (streamAbort) {
      streamAbort.abort();
      setStreamAbort(null);
      setBusy(false);
    }
  }

  const fileInputRef = useRef();

  function handleCopy(code) {
    navigator.clipboard.writeText(code);
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

  function MessageBubble({ m, i }) {
    // --- Always call hooks before any return! ---
    const cleanText = cleanAssistantText(m.text || "");
    const citations = extractCitations(m.meta);

    // Only animate the last assistant message if it's busy (streaming)
    const isLastAssistant =
      i ===
      messages
        .map((msg, idx) => (msg.role === "assistant" ? idx : -1))
        .filter((idx) => idx !== -1)
        .slice(-1)[0];
    const shouldAnimate = m.busy && isLastAssistant;

    // Always call the hook, but use the result only if needed
    const animatedText = useTypewriter(cleanText, shouldAnimate, 35);

    if (m.role === "system") {
      return <div className={styles.systemMsg}>{m.text}</div>;
    }
    const isUser = m.role === "user";
    if (isUser) {
      return (
        <div>
          <div className={styles.bubbleUser}>
            <div className={styles.userHeader}>You</div>
            <div dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }} />
          </div>
        </div>
      );
    }

    return (
      <div>
        <div
          className={styles.bubbleAssistant}
          style={{ position: "relative" }}
        >
          <div className={styles.assistantHeader}>Assistant</div>
          <div
            dangerouslySetInnerHTML={{
              __html: renderMarkdown(shouldAnimate ? animatedText : cleanText),
            }}
          />
          {/* Citations */}
          {citations.length > 0 && (
            <div className={styles.citations}>
              {citations.map((c, idx) => (
                <span
                  key={c.key}
                  title={`Source: ${c.file}${c.page ? `, page ${c.page}` : ""}`}
                  className={styles.citationChip}
                  style={{ cursor: c.source ? "pointer" : "default" }}
                  onClick={() => c.source && window.open(c.source, "_blank")}
                >
                  {c.label}{" "}
                  <span className={styles.citationFile}>({c.file})</span>
                </span>
              ))}
            </div>
          )}
          {/* Copy button for code blocks */}
          {m.text?.includes("```") &&
            m.text.split(/```/).map((block, idx) =>
              idx % 2 === 1 ? (
                <button
                  key={idx}
                  onClick={() => handleCopy(block)}
                  className={styles.copyBtn}
                  style={{ right: 8 + idx * 60 }}
                >
                  Copy
                </button>
              ) : null,
            )}
          {/* Regenerate button */}
          <button
            onClick={(e) => ask(i, e)}
            className={styles.regenBtn}
            disabled={busy}
          >
            🔄 Regenerate
          </button>
          {/* Suggested search */}
          {m.meta?.suggested_search && (
            <div className={styles.suggestedSearch}>
              <a
                href={m.meta.suggested_search}
                target="_blank"
                rel="noreferrer"
                className={styles.suggestedSearchLink}
              >
                🔎 Search on Google
              </a>
            </div>
          )}
        </div>
      </div>
    );
  }

  function TypingBubble() {
    const [dots, setDots] = useState("");
    useEffect(() => {
      const id = setInterval(() => {
        setDots((d) => (d.length >= 3 ? "" : d + "."));
      }, 350);
      return () => clearInterval(id);
    }, []);
    return (
      <div className={styles.typingBubble}>
        <div className={styles.assistantHeader}>Assistant</div>
        <div>Thinking{dots}</div>
      </div>
    );
  }

  // Show typing bubble if any assistant message is busy
  const showTyping =
    busy || messages.some((m) => m.role === "assistant" && m.busy);

  // Helper to format file size
  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  // Drag-and-drop state
  const [dragActive, setDragActive] = useState(false);

  // Handle file selection
  function handleFiles(files) {
    const newFiles = Array.from(files)
      .filter((f) => f.type === "application/pdf")
      .filter(
        (f) =>
          !attachments.some(
            (a) => a.file.name === f.name && a.file.size === f.size,
          ),
      );
    if (newFiles.length === 0) return;
    setAttachments((atts) => [
      ...atts,
      ...newFiles.map((f) => ({
        file: f,
        id: `${f.name}-${f.size}-${Date.now()}-${Math.random()}`,
        status: "pending",
      })),
    ]);
  }

  // Remove attachment
  function removeAttachment(id) {
    setAttachments((atts) => atts.filter((a) => a.id !== id));
  }

  // Drag-and-drop handlers
  function onDragOver(e) {
    e.preventDefault();
    setDragActive(true);
  }
  function onDragLeave(e) {
    e.preventDefault();
    setDragActive(false);
  }
  function onDrop(e) {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer?.files) handleFiles(e.dataTransfer.files);
  }

  async function ingestAttachments() {
    if (!collection) return;
    // Mark all as uploading
    setAttachments((atts) =>
      atts.map((a) =>
        a.status === "pending" ? { ...a, status: "uploading" } : a,
      ),
    );
    const filesToUpload = attachments.filter((a) => a.status === "pending");
    if (filesToUpload.length === 0) return;

    const fd = new FormData();
    fd.append("collection", collection);
    filesToUpload.forEach((a) => fd.append("files", a.file));

    let summary = [];
    let totalChunks = 0;
    try {
      const res = await fetch(apiBaseRaw + "/ingest", {
        method: "POST",
        body: fd,
      });
      const data = await res.json().catch(() => ({}));
      console.log("[Ingest response]", data);

      // Backend should return per-file status, e.g.:
      // { files: [{filename, chunks, error}], total_chunks }
      if (Array.isArray(data.files)) {
        setAttachments((atts) =>
          atts.map((a) => {
            const fileRes = data.files.find((f) => f.filename === a.file.name);
            if (!fileRes) return a;
            if (fileRes.error) {
              return { ...a, status: "error", error: fileRes.error };
            }
            return { ...a, status: "done", chunks: fileRes.chunks };
          }),
        );
        summary = data.files.map((f) =>
          f.error
            ? `${f.filename} (error: ${f.error})`
            : `${f.filename} (${f.chunks} chunks)`,
        );
        totalChunks =
          data.total_chunks ||
          data.files.reduce((sum, f) => sum + (f.chunks || 0), 0);
      } else {
        // Fallback: treat all as success
        setAttachments((atts) =>
          atts.map((a) =>
            filesToUpload.some((f) => f.id === a.id)
              ? { ...a, status: "done", chunks: data.chunks || 0 }
              : a,
          ),
        );
        summary = filesToUpload.map(
          (a) => `${a.file.name} (${data.chunks || "?"} chunks)`,
        );
        totalChunks = data.chunks || 0;
      }

      // System message
      setMessages((msgs) => [
        ...msgs,
        {
          role: "system",
          text: `Ingested ${filesToUpload.length} file${
            filesToUpload.length > 1 ? "s" : ""
          } into ‘${collection}’: ${summary.join(
            ", ",
          )}. Total chunks: ${totalChunks}.`,
          muted: true,
        },
      ]);
      // Optionally clear attachments after a short delay
      setTimeout(() => {
        setAttachments((atts) => atts.filter((a) => a.status !== "done"));
      }, 1200);
    } catch (e) {
      setAttachments((atts) =>
        atts.map((a) =>
          filesToUpload.some((f) => f.id === a.id)
            ? { ...a, status: "error", error: e.message || "Network error" }
            : a,
        ),
      );
      setMessages((msgs) => [
        ...msgs,
        {
          role: "system",
          text: `⚠️ Ingest failed: ${e.message || e}`,
        },
      ]);
    }
  }

  return (
    <>
      {/* Sidebar (left) */}
      <Sidebar
        sidebarOpen={sidebarOpen}
        setSidebarOpen={setSidebarOpen}
        logs={logs}
        collection={collection}
        setCollection={setCollection}
        apiBase={apiBaseRaw}
        onSystemMessage={setSystemMsg}
        topK={topK}
        setTopK={setTopK}
        simThreshold={simThreshold}
        setSimThreshold={setSimThreshold}
      />
      {/* Main Chat Area */}
      <main className={styles.main}>
        {/* Header */}
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

        {/* Chat messages */}
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
            transition: "background 0.2s",
          }}
        >
          <div
            style={{
              maxWidth: 700,
              margin: "0 auto",
              width: "100%",
              padding: "0 24px",
            }}
          >
            {messages.length === 0 && (
              <div className={styles.emptyMsg}>
                No messages yet. Upload a PDF and ask something.
              </div>
            )}
            {messages.map((m, i) => (
              <MessageBubble key={i} m={m} i={i} />
            ))}
            {showTyping && <TypingBubble />}
            {showTyping && streamAbort && (
              <div className={styles.stopBtnWrapper}>
                <button className={styles.stopBtn} onClick={cancelStream}>
                  ⏹ Stop
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Sticky Composer */}
        <div
          className={styles.composer}
          style={{
            border: dragActive ? "2px dashed #2563eb" : undefined,
            background: dragActive ? "#e8f0fe" : undefined,
            transition: "border 0.2s, background 0.2s",
          }}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        >
          {/* Attachment chips */}
          {attachments.length > 0 && (
            <div
              style={{
                display: "flex",
                gap: 8,
                marginBottom: 8,
                flexWrap: "wrap",
              }}
            >
              {attachments.map((att) => (
                <div
                  key={att.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    background: "var(--chip-bg)",
                    borderRadius: 8,
                    padding: "4px 10px",
                    fontSize: 14,
                    color: "var(--chip-text)",
                    maxWidth: 220,
                    minWidth: 0,
                    opacity: att.status === "done" ? 0.6 : 1,
                    border:
                      att.status === "error" ? "1px solid #c00" : undefined,
                  }}
                  title={att.file.name}
                >
                  <span
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      maxWidth: 120,
                      display: "inline-block",
                    }}
                  >
                    📄 {att.file.name}
                  </span>
                  <span
                    style={{
                      fontSize: 12,
                      marginLeft: 6,
                      opacity: 0.7,
                    }}
                  >
                    {formatSize(att.file.size)}
                  </span>
                  {att.status === "uploading" && (
                    <span
                      style={{
                        fontSize: 12,
                        marginLeft: 8,
                        color: "#888",
                      }}
                    >
                      Uploading…
                    </span>
                  )}
                  {att.status === "done" && (
                    <span
                      style={{
                        fontSize: 12,
                        marginLeft: 8,
                        color: "#22c55e",
                      }}
                    >
                      ✓ {att.chunks ? `${att.chunks} chunks` : "Done"}
                    </span>
                  )}
                  {att.status === "error" && (
                    <span
                      style={{
                        fontSize: 12,
                        marginLeft: 8,
                        color: "#c00",
                      }}
                    >
                      {att.error || "Error"}
                    </span>
                  )}
                  <button
                    onClick={() => removeAttachment(att.id)}
                    style={{
                      background: "none",
                      border: "none",
                      color: "#888",
                      fontSize: 16,
                      marginLeft: 6,
                      cursor: "pointer",
                    }}
                    disabled={att.status === "uploading"}
                    aria-label="Remove"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Inline warning if no collection */}
          {!collection && attachments.length > 0 && (
            <div
              style={{
                color: "#c00",
                fontSize: 13,
                marginBottom: 8,
              }}
            >
              Choose a collection first.
            </div>
          )}

          {/* File input and upload button */}
          <form
            className={styles.composerForm}
            onSubmit={(e) => {
              e.preventDefault();
              ask(null, e);
            }}
            style={{ alignItems: "flex-end" }}
          >
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className={styles.paperclipBtn}
              aria-label="Attach PDF"
              disabled={attachments.some((a) => a.status === "uploading")}
            >
              📎
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf"
              multiple
              style={{ display: "none" }}
              onChange={(e) => handleFiles(e.target.files)}
            />
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask something about your document…"
              rows={1}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(null, e);
                }
              }}
              className={styles.textarea}
              disabled={busy}
            />
            <button
              className={styles.sendBtn}
              type="submit"
              disabled={busy || !question.trim()}
              aria-label="Send"
            >
              ➤
            </button>
            <button
              type="button"
              className={styles.fileIngestBtn}
              style={{
                background: attachments.some((a) => a.status === "uploading")
                  ? "var(--button-disabled-bg)"
                  : "#22c55e",
                marginLeft: 8,
                minWidth: 80,
              }}
              disabled={
                attachments.length === 0 ||
                attachments.some((a) => a.status === "uploading") ||
                !collection
              }
              onClick={ingestAttachments}
            >
              {attachments.some((a) => a.status === "uploading")
                ? "Uploading…"
                : "Upload"}
            </button>
          </form>
          <div className={styles.composerHint}>
            You can drag and drop PDFs here. If you see “No extractable text”,
            it’s probably a scanned PDF. We can add OCR later.
          </div>
        </div>
      </main>
    </>
  );
}

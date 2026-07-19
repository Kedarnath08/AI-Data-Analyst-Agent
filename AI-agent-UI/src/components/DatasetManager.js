"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./CollectionManager.module.css";
import {
  connectDatabase,
  deleteDataset,
  fetchDatasets,
  getDataset,
  uploadDataset,
} from "../utils/datasets";

const ACCEPT = ".csv,.xlsx,.xls,.pdf,.docx";

export default function DatasetManager({
  apiBase,
  dataset,
  setDataset,
  onSystemMessage,
}) {
  const [datasets, setDatasets] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState("");
  const [showDbForm, setShowDbForm] = useState(false);
  const fileRef = useRef(null);

  const load = useCallback(
    async (selectId) => {
      setLoading(true);
      setErr("");
      try {
        const data = await fetchDatasets(apiBase);
        const list = data.datasets || [];
        setDatasets(list);

        // Prefer an explicit target, then the current selection, then the one
        // remembered from a previous session, then the first available.
        const remembered = localStorage.getItem("analyst_dataset_id");
        const target = selectId || dataset?.id || remembered;
        const found = list.find((d) => d.id === target);
        if (found) {
          // Fetch full detail so schema/columns are available for the preview.
          try {
            setDataset(await getDataset(apiBase, found.id));
          } catch {
            setDataset(found);
          }
        } else if (list.length > 0 && !dataset) {
          try {
            setDataset(await getDataset(apiBase, list[0].id));
          } catch {
            setDataset(list[0]);
          }
        } else if (list.length === 0) {
          setDataset(null);
        }
      } catch (e) {
        setErr(e.message || "Failed to load datasets");
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [apiBase],
  );

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

  async function onPickFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    try {
      const res = await uploadDataset(apiBase, file);
      onSystemMessage?.(
        `Uploaded “${file.name}” → ${res.tables.length} table(s): ${res.tables
          .map((t) => t.name)
          .join(", ")}`,
      );
      await load(res.dataset_id);
    } catch (e2) {
      onSystemMessage?.(`⚠️ Upload failed: ${e2.message || e2}`);
    } finally {
      setUploading(false);
    }
  }

  async function selectDataset(id) {
    if (!id) return setDataset(null);
    try {
      // Fetch full detail so the sidebar can show tables/schema.
      const detail = await getDataset(apiBase, id);
      setDataset(detail);
    } catch (e) {
      onSystemMessage?.(`⚠️ ${e.message || e}`);
    }
  }

  async function removeDataset() {
    if (!dataset) return;
    if (!window.confirm(`Remove dataset “${dataset.name}”?`)) return;
    try {
      await deleteDataset(apiBase, dataset.id);
      onSystemMessage?.(`Removed “${dataset.name}”`);
      setDataset(null);
      await load();
    } catch (e) {
      onSystemMessage?.(`⚠️ ${e.message || e}`);
    }
  }

  return (
    <div className={styles.managerRoot}>
      <div className={styles.sectionTitle}>Datasets</div>
      {err && (
        <div className={styles.inlineError}>
          {err}
          <button className={styles.actionBtn} onClick={() => load()}>
            Retry
          </button>
        </div>
      )}

      <div
        style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}
      >
        <select
          className={styles.actionInput}
          value={dataset?.id || ""}
          onChange={(e) => selectDataset(e.target.value)}
          disabled={loading || uploading || datasets.length === 0}
          style={{ minWidth: 0, flex: 1 }}
        >
          {datasets.length === 0 && <option value="">No datasets</option>}
          {datasets.map((d) => (
            <option key={d.id} value={d.id}>
              {d.kind === "database" ? "🗄️ " : "📄 "}
              {d.name}
            </option>
          ))}
        </select>
        <button
          className={styles.actionBtn}
          onClick={removeDataset}
          disabled={!dataset}
          title="Remove selected dataset"
        >
          🗑️
        </button>
      </div>

      <div className={styles.actions}>
        <button
          className={styles.actionBtn}
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          style={{ flex: 1 }}
        >
          {uploading ? "Uploading…" : "＋ Upload file"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPT}
          style={{ display: "none" }}
          onChange={onPickFile}
        />
      </div>

      <button
        className={styles.actionBtn}
        onClick={() => setShowDbForm((v) => !v)}
        style={{ width: "100%", marginTop: 6 }}
      >
        {showDbForm ? "Cancel" : "🗄️ Connect database"}
      </button>

      {showDbForm && (
        <ConnectDbForm
          apiBase={apiBase}
          onDone={async (res) => {
            setShowDbForm(false);
            onSystemMessage?.(
              `Connected ${res.engine} database “${res.name}” (${res.tables.length} table(s))`,
            );
            await load(res.dataset_id);
          }}
          onError={(m) => onSystemMessage?.(`⚠️ ${m}`)}
        />
      )}
    </div>
  );
}

function ConnectDbForm({ apiBase, onDone, onError }) {
  const [engine, setEngine] = useState("postgres");
  const [form, setForm] = useState({
    name: "",
    host: "localhost",
    port: 5432,
    user: "",
    password: "",
    database: "",
  });
  const [busy, setBusy] = useState(false);

  const isSqlite = engine === "sqlite";
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  function changeEngine(e) {
    const next = e.target.value;
    setEngine(next);
    setForm((f) => ({
      ...f,
      port: next === "postgres" ? 5432 : next === "mysql" ? 3306 : "",
    }));
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const payload = {
        engine,
        name: form.name || undefined,
        database: form.database,
        ...(isSqlite
          ? {}
          : {
              host: form.host,
              port: Number(form.port) || undefined,
              user: form.user,
              password: form.password,
            }),
      };
      onDone(await connectDatabase(apiBase, payload));
    } catch (e2) {
      onError(e2.message || String(e2));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} style={{ marginTop: 8, display: "grid", gap: 6 }}>
      <select className={styles.actionInput} value={engine} onChange={changeEngine}>
        <option value="postgres">PostgreSQL</option>
        <option value="mysql">MySQL</option>
        <option value="sqlite">SQLite (file)</option>
      </select>
      <input
        className={styles.actionInput}
        placeholder="Display name (optional)"
        value={form.name}
        onChange={set("name")}
      />
      <input
        className={styles.actionInput}
        placeholder={isSqlite ? "Path to .db file" : "Database name"}
        value={form.database}
        onChange={set("database")}
        required
      />
      {!isSqlite && (
        <>
          <input
            className={styles.actionInput}
            placeholder="Host"
            value={form.host}
            onChange={set("host")}
          />
          <input
            className={styles.actionInput}
            placeholder="Port"
            value={form.port}
            onChange={set("port")}
          />
          <input
            className={styles.actionInput}
            placeholder="User"
            value={form.user}
            onChange={set("user")}
          />
          <input
            className={styles.actionInput}
            type="password"
            placeholder="Password"
            value={form.password}
            onChange={set("password")}
          />
        </>
      )}
      <button className={styles.actionBtn} type="submit" disabled={busy}>
        {busy ? "Connecting…" : "Connect (read-only)"}
      </button>
    </form>
  );
}

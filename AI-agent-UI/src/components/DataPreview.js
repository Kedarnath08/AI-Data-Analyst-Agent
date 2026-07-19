"use client";
import { useCallback, useEffect, useState } from "react";
import styles from "../app/page.module.css";
import { previewDataset } from "../utils/datasets";

function cellText(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/**
 * Collapsible preview of the selected dataset: a table picker, the column
 * list (so users know what they can ask about), and a sample of rows.
 */
export default function DataPreview({ apiBase, dataset }) {
  const tables = dataset?.tables || [];
  const [open, setOpen] = useState(false);
  const [table, setTable] = useState(tables[0]?.name || "");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  // Reset when the dataset changes.
  useEffect(() => {
    setTable(dataset?.tables?.[0]?.name || "");
    setData(null);
    setErr("");
  }, [dataset?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    if (!dataset || !table) return;
    setLoading(true);
    setErr("");
    try {
      setData(await previewDataset(apiBase, dataset.id, table));
    } catch (e) {
      setErr(e.message || "Failed to load preview");
    } finally {
      setLoading(false);
    }
  }, [apiBase, dataset, table]);

  // Fetch when opened, or when the chosen table changes while open.
  useEffect(() => {
    if (open) load();
  }, [open, table, load]);

  if (!dataset) return null;

  const columns =
    dataset.schema?.[table] ||
    tables.find((t) => t.name === table)?.columns ||
    [];

  return (
    <div className={styles.previewWrap}>
      <button
        className={styles.previewToggle}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>{open ? "▾" : "▸"}</span>
        <span>Preview data</span>
        <span className={styles.previewMeta}>
          {tables.length} table{tables.length === 1 ? "" : "s"}
        </span>
      </button>

      {open && (
        <div className={styles.previewBody}>
          {tables.length > 1 && (
            <select
              className={styles.previewSelect}
              value={table}
              onChange={(e) => setTable(e.target.value)}
            >
              {tables.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}
                  {typeof t.row_count === "number" ? ` (${t.row_count} rows)` : ""}
                </option>
              ))}
            </select>
          )}

          {columns.length > 0 && (
            <div className={styles.columnChips}>
              {columns.map((c) => (
                <span key={c.name} className={styles.columnChip} title={c.type}>
                  {c.name}
                  <span className={styles.columnType}>{c.type}</span>
                </span>
              ))}
            </div>
          )}

          {loading && <div className={styles.previewNote}>Loading preview…</div>}
          {err && <div className={styles.previewError}>{err}</div>}

          {data && !loading && (
            <>
              <div className={styles.previewTableScroll}>
                <table className={styles.previewTable}>
                  <thead>
                    <tr>
                      {data.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((row, i) => (
                      <tr key={i}>
                        {row.map((cell, j) => (
                          <td key={j}>{cellText(cell)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className={styles.previewNote}>
                Showing {data.row_count} row{data.row_count === 1 ? "" : "s"}
                {typeof tables.find((t) => t.name === table)?.row_count ===
                "number"
                  ? ` of ${tables.find((t) => t.name === table).row_count}`
                  : ""}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

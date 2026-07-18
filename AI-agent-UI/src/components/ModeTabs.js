"use client";
import styles from "../app/page.module.css";

const MODES = [
  { id: "documents", label: "📄 Document Chat" },
  { id: "analyst", label: "📊 Data Analyst" },
];

export default function ModeTabs({ mode, setMode }) {
  return (
    <div className={styles.modeTabs} role="tablist" aria-label="Workspace mode">
      {MODES.map((m) => (
        <button
          key={m.id}
          role="tab"
          aria-selected={mode === m.id}
          className={`${styles.modeTab} ${
            mode === m.id ? styles.modeTabActive : ""
          }`}
          onClick={() => setMode(m.id)}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}

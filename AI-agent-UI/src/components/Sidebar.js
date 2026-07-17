import styles from "../app/page.module.css";
import CollectionManager from "./CollectionManager";

export default function Sidebar({
  sidebarOpen,
  logs,
  collection,
  setCollection,
  apiBase,
  onSystemMessage,
  topK,
  setTopK,
  simThreshold,
  setSimThreshold,
}) {
  return (
    <aside
      className={`${styles.sidebar} ${
        !sidebarOpen ? styles.sidebarClosed : ""
      }`}
    >
      <div
        style={{
          padding: 20,
          borderBottom: "1px solid var(--sidebar-border)",
        }}
      >
        <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 12 }}>
          Gemicone
        </h2>
        <button
          className={styles.newChatBtn}
          onClick={() => window.location.reload()}
        >
          + New Chat
        </button>
        {/* Collection Manager */}
        <CollectionManager
          apiBase={apiBase}
          currentCollection={collection}
          setCurrentCollection={setCollection}
          onSystemMessage={onSystemMessage}
        />
        <div className={styles.settingsTitle}>
          <b>Settings</b>
        </div>
        <div style={{ fontSize: 13, marginBottom: 8 }}>
          <label>top_k</label>
          <input
            type="number"
            min={1}
            max={20}
            value={topK}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              if (!Number.isNaN(v)) setTopK(Math.min(20, Math.max(1, v)));
            }}
            className={styles.settingsInputShort}
          />
        </div>
        <div style={{ fontSize: 13, marginBottom: 8 }}>
          <label>sim_threshold</label>
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={simThreshold}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              if (!Number.isNaN(v)) setSimThreshold(Math.min(1, Math.max(0, v)));
            }}
            className={styles.settingsInputShort}
          />
        </div>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        <div className={styles.logsTitle}>
          <b>Logs</b>
        </div>
        <ul className={styles.logsList}>
          {logs.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      </div>
    </aside>
  );
}

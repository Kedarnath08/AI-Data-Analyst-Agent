import React, { useEffect, useState } from "react";
import styles from "./CollectionManager.module.css";
import {
  fetchCollections,
  createCollection as apiCreateCollection,
  clearCollection as apiClearCollection,
} from "../utils/collections";

const COLLECTION_KEY = "ragui_current_collection";
const LOCAL_COLLECTIONS_KEY = "ragui_local_collections";

export default function CollectionManager({
  apiBase,
  currentCollection,
  setCurrentCollection,
  onSystemMessage,
}) {
  const [collections, setCollections] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  // Helper: get local collections
  function getLocalCollections() {
    try {
      return JSON.parse(localStorage.getItem(LOCAL_COLLECTIONS_KEY) || "[]");
    } catch {
      return [];
    }
  }
  function saveLocalCollection(name) {
    const list = getLocalCollections();
    if (!list.includes(name)) {
      localStorage.setItem(
        LOCAL_COLLECTIONS_KEY,
        JSON.stringify([...list, name])
      );
    }
  }

  // Load collections on mount and when needed
  async function loadCollections() {
    setLoading(true);
    setErr("");
    try {
      const data = await fetchCollections(apiBase);
      let backendCols = data.collections || data;
      // Merge with local: prefer backend version if exists
      const localCols = getLocalCollections()
        .filter((name) => !backendCols.some((bc) => bc.name === name))
        .map((name) => ({
          name,
          vector_count: 0,
          local: true,
        }));
      const allCols = [...backendCols, ...localCols];
      setCollections(allCols);
      if (!currentCollection && allCols.length > 0) {
        selectCollection(allCols[0].name);
      }
    } catch (e) {
      setErr(e.message || "Failed to load collections");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadCollections();
    // eslint-disable-next-line
  }, [apiBase]);

  // Persist selection
  useEffect(() => {
    if (currentCollection)
      localStorage.setItem(COLLECTION_KEY, currentCollection);
  }, [currentCollection]);

  // On mount, restore selection
  useEffect(() => {
    const saved = localStorage.getItem(COLLECTION_KEY);
    if (saved) setCurrentCollection(saved);
    // eslint-disable-next-line
  }, []);

  async function handleCreate() {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await apiCreateCollection(apiBase, newName.trim());
      saveLocalCollection(newName.trim());
      setNewName("");
      onSystemMessage?.(`Created collection ‘${newName.trim()}’`);
      await loadCollections();
      selectCollection(newName.trim());
    } catch (e) {
      onSystemMessage?.(`Failed to create: ${e.message}`);
    } finally {
      setCreating(false);
    }
  }

  async function handleClear() {
    if (!currentCollection) return;
    if (!window.confirm(`Clear all data in ‘${currentCollection}’?`)) return;
    try {
      await apiClearCollection(apiBase, currentCollection);
      onSystemMessage?.(`Cleared collection ‘${currentCollection}’`);
      await loadCollections();
    } catch (e) {
      onSystemMessage?.(`Failed to clear: ${e.message}`);
    }
  }

  function selectCollection(name) {
    setCurrentCollection(name);
    onSystemMessage?.(`Switched to collection ‘${name}’`);
  }

  return (
    <div className={styles.managerRoot}>
      <div className={styles.sectionTitle}>Collections</div>
      {err && (
        <div className={styles.inlineError}>
          {err}
          <button className={styles.actionBtn} onClick={loadCollections}>
            Retry
          </button>
        </div>
      )}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 8,
        }}
      >
        <select
          className={styles.actionInput}
          value={currentCollection || ""}
          onChange={(e) => selectCollection(e.target.value)}
          disabled={loading || creating || collections.length === 0}
          style={{ minWidth: 0, flex: 1 }}
        >
          {collections.length === 0 && <option value="">No collections</option>}
          {collections.map((col) => {
            const name = col.name || col;
            const count = col.count ?? col.vectors ?? col.vector_count ?? null;
            const isEmpty =
              (col.local && (!count || count === 0)) ||
              (!col.local && (count === 0 || count === null));
            return (
              <option key={name} value={name}>
                {name}{" "}
                {isEmpty ? "(Empty)" : count !== null ? `(${count})` : ""}
              </option>
            );
          })}
        </select>
        <button
          className={styles.actionBtn}
          onClick={handleClear}
          disabled={!currentCollection || creating}
          title="Clear selected collection"
        >
          🧹
        </button>
      </div>
      <div className={styles.actions}>
        <input
          type="text"
          placeholder="New collection…"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          className={styles.actionInput}
          disabled={creating}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleCreate();
          }}
        />
        <button
          className={styles.actionBtn}
          onClick={handleCreate}
          disabled={creating || !newName.trim()}
          title="Create collection"
        >
          +
        </button>
      </div>
    </div>
  );
}

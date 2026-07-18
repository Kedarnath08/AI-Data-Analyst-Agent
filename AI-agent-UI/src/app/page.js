"use client";
import { useState } from "react";
import DocumentChat from "../components/DocumentChat";
import DataAnalyst from "../components/DataAnalyst";
import styles from "./page.module.css";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8090";

/**
 * Shell for the unified app. Owns the chrome-level state (theme, sidebar,
 * which workspace is active) and renders one of the two modes:
 *   - documents: RAG chat over ingested PDFs
 *   - analyst:   agentic data analysis over datasets / live databases
 * Both talk to the same backend.
 */
export default function HomePage() {
  const [mode, setMode] = useState("documents");
  const [theme, setTheme] = useState("light");
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const shared = {
    apiBase: API_BASE,
    theme,
    setTheme,
    sidebarOpen,
    setSidebarOpen,
    mode,
    setMode,
  };

  return (
    <div className={`${styles.root} ${styles[theme]}`}>
      {mode === "documents" ? (
        <DocumentChat {...shared} />
      ) : (
        <DataAnalyst {...shared} />
      )}
    </div>
  );
}

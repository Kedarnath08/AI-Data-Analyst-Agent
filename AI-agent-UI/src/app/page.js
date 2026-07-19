"use client";
import { useEffect, useState } from "react";
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
  // Start with the SSR default, then restore the saved choices after mount —
  // reading localStorage during render would break hydration.
  const [mode, setMode] = useState("documents");
  const [theme, setTheme] = useState("light");
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    const savedMode = localStorage.getItem("ui_mode");
    if (savedMode === "documents" || savedMode === "analyst") setMode(savedMode);
    const savedTheme = localStorage.getItem("ui_theme");
    if (savedTheme === "light" || savedTheme === "dark") setTheme(savedTheme);
  }, []);

  useEffect(() => {
    localStorage.setItem("ui_mode", mode);
  }, [mode]);

  useEffect(() => {
    localStorage.setItem("ui_theme", theme);
  }, [theme]);

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

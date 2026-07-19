async function handle(res) {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail =
      typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchDatasets(apiBase) {
  return handle(await fetch(`${apiBase}/datasets/`));
}

export async function uploadDataset(apiBase, file, name) {
  const fd = new FormData();
  fd.append("file", file, file.name);
  if (name) fd.append("name", name);
  return handle(
    await fetch(`${apiBase}/datasets/upload`, { method: "POST", body: fd }),
  );
}

export async function connectDatabase(apiBase, connection) {
  return handle(
    await fetch(`${apiBase}/datasets/connect_db`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(connection),
    }),
  );
}

export async function getDataset(apiBase, id) {
  return handle(await fetch(`${apiBase}/datasets/${encodeURIComponent(id)}`));
}

export async function previewDataset(apiBase, id, table, limit = 25) {
  const params = new URLSearchParams();
  if (table) params.set("table", table);
  params.set("limit", String(limit));
  return handle(
    await fetch(
      `${apiBase}/datasets/${encodeURIComponent(id)}/preview?${params}`,
    ),
  );
}

export async function deleteDataset(apiBase, id) {
  return handle(
    await fetch(`${apiBase}/datasets/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  );
}

/**
 * Ask the analyst with live progress. `onEvent({type, ...})` fires for each
 * step (thinking / tool_start / tool_end / waiting) and finally for the
 * result, so the UI can show what the agent is doing instead of a spinner.
 * Resolves with the final payload.
 */
export async function askAnalystStream(
  apiBase,
  datasetId,
  question,
  onEvent,
  signal,
) {
  const res = await fetch(`${apiBase}/ask_stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ dataset_id: datasetId, question }),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = null;
  let final = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop(); // keep any partial line for the next chunk

    for (const raw of lines) {
      const line = raw.trim();
      if (!line) continue;
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
        continue;
      }
      if (!line.startsWith("data:")) continue;

      let payload;
      try {
        payload = JSON.parse(line.slice(5).trim());
      } catch {
        continue;
      }
      if (event === "final") {
        final = payload.payload;
      } else {
        onEvent?.({ type: event, ...payload });
      }
    }
  }

  if (!final) throw new Error("Stream ended before the agent returned a result.");
  return final;
}

export async function askAnalyst(apiBase, datasetId, question, signal) {
  return handle(
    await fetch(`${apiBase}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataset_id: datasetId, question }),
      signal,
    }),
  );
}

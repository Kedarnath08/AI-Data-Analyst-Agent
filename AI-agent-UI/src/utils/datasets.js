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

export async function deleteDataset(apiBase, id) {
  return handle(
    await fetch(`${apiBase}/datasets/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  );
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

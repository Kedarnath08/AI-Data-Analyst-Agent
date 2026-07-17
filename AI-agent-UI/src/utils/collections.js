export async function fetchCollections(apiBase) {
  const url = `${apiBase}/collections/`;
  console.log("[fetchCollections] Fetching from:", url);
  try {
    const res = await fetch(url, {
      method: "GET",
      mode: "cors",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
    });
    console.log(
      "[fetchCollections] Response status:",
      res.status,
      res.statusText,
    );
    if (!res.ok) {
      const errData = await res
        .json()
        .catch(() => ({ detail: res.statusText }));
      console.error("[fetchCollections] Error response:", errData);
      throw new Error(
        errData.detail || `HTTP ${res.status}: ${res.statusText}`,
      );
    }
    const data = await res.json();
    console.log("[fetchCollections] Success:", data);
    return data;
  } catch (err) {
    console.error("[fetchCollections] Fetch error:", err);
    throw err;
  }
}

export async function createCollection(apiBase, name) {
  const url = `${apiBase}/collections/`;
  console.log("[createCollection] POST to:", url, "with name:", name);
  try {
    const res = await fetch(url, {
      method: "POST",
      mode: "cors",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    console.log("[createCollection] Response status:", res.status);
    if (!res.ok) {
      const errData = await res
        .json()
        .catch(() => ({ detail: res.statusText }));
      console.error("[createCollection] Error response:", errData);
      throw new Error(
        errData.detail || `HTTP ${res.status}: ${res.statusText}`,
      );
    }
    const data = await res.json();
    console.log("[createCollection] Success:", data);
    return data;
  } catch (err) {
    console.error("[createCollection] Fetch error:", err);
    throw err;
  }
}

export async function clearCollection(apiBase, name) {
  const url = `${apiBase}/collections/${encodeURIComponent(name)}/`;
  console.log("[clearCollection] DELETE:", url);
  try {
    const res = await fetch(url, {
      method: "DELETE",
      mode: "cors",
      credentials: "include",
    });
    console.log("[clearCollection] Response status:", res.status);
    if (!res.ok) {
      const errData = await res
        .json()
        .catch(() => ({ detail: res.statusText }));
      console.error("[clearCollection] Error response:", errData);
      throw new Error(
        errData.detail || `HTTP ${res.status}: ${res.statusText}`,
      );
    }
    const data = await res.json();
    console.log("[clearCollection] Success:", data);
    return data;
  } catch (err) {
    console.error("[clearCollection] Fetch error:", err);
    throw err;
  }
}

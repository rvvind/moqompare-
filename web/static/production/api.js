export async function getRegistrySnapshot() {
  const response = await fetch("/registry/api/status", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`registry status failed (${response.status})`);
  }
  return response.json();
}

export async function setProgramRoute(streamId) {
  const response = await fetch("/registry/api/routes/program", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ stream_id: streamId }),
  });
  if (!response.ok) {
    throw new Error(`route update failed (${response.status})`);
  }
  return response.json();
}

export async function setProgramModifier(streamId) {
  const response = await fetch("/registry/api/routes/program/modifier", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(streamId ? { stream_id: streamId } : {}),
  });
  if (!response.ok) {
    throw new Error(`modifier update failed (${response.status})`);
  }
  return response.json();
}

export function connectRegistryEvents({ onSnapshot, onError }) {
  const events = new EventSource("/registry/api/events");
  events.addEventListener("snapshot", (event) => {
    try {
      const snapshot = JSON.parse(event.data);
      onSnapshot?.(snapshot);
    } catch (error) {
      console.error("failed to parse registry snapshot", error);
    }
  });
  events.addEventListener("keepalive", () => {});
  events.onerror = (event) => {
    onError?.(event);
  };
  return events;
}

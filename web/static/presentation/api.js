const JSON_HEADERS = { "Content-Type": "application/json" };

export async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

export async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

export function connectPresentationEvents(onUpdate) {
  const events = new EventSource("/metrics/presentation/events");
  events.addEventListener("update", (event) => {
    try {
      onUpdate(JSON.parse(event.data));
    } catch (error) {
      console.error("presentation update parse error", error);
    }
  });
  return events;
}

export function formatSeconds(seconds, fallback = "measuring…") {
  if (typeof seconds !== "number" || Number.isNaN(seconds)) return fallback;
  if (seconds >= 10) return `${Math.round(seconds)}s`;
  return `${seconds.toFixed(1)}s`;
}

export function formatMilliseconds(ms, fallback = "measuring…") {
  if (typeof ms !== "number" || Number.isNaN(ms)) return fallback;
  if (ms >= 10000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

export function formatBitrate(bps, fallback = "measuring…") {
  if (typeof bps !== "number" || Number.isNaN(bps) || bps <= 0) return fallback;
  if (bps >= 1000000) return `${(bps / 1000000).toFixed(1)} Mbps`;
  return `${Math.round(bps / 1000)} kbps`;
}

export function metricTone(kind, value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "muted";
  if (kind === "liveLatency" || kind === "drift") {
    if (value < 1.5) return "good";
    if (value < 5) return "warn";
    return "bad";
  }
  if (kind === "startup") {
    if (value < 1800) return "good";
    if (value < 3500) return "warn";
    return "bad";
  }
  if (kind === "stallCount") {
    if (value <= 0) return "good";
    if (value <= 1) return "warn";
    return "bad";
  }
  return "neutral";
}

export function impairmentTone(profile) {
  if (!profile || profile === "baseline") return "good";
  if (profile === "stale_manifest" || profile === "outage") return "bad";
  return "warn";
}

export async function getPresentationSnapshot() {
  return getJSON("/metrics/presentation/snapshot");
}

export async function setPresentationState(statePatch) {
  return postJSON("/metrics/presentation/state", { state: statePatch });
}

export async function pushPresentationTelemetry(telemetry) {
  return postJSON("/metrics/presentation/telemetry", telemetry);
}

export async function applyImpairment(profile) {
  return postJSON(`/impair/${profile}`, {});
}

export async function getImpairmentStatus() {
  return getJSON("/impair/status");
}

import { connectRegistryEvents, getRegistrySnapshot } from "./api.js";
import { ensureWatchReady, readWatchState, retuneWatch } from "./watch.js";

const PROGRAM_RECONNECT_DELAYS_MS = [1200, 2400, 4000, 6500];

const state = {
  program: null,
  events: [],
};

const refs = {
  health: document.getElementById("program-health"),
  healthLabel: document.getElementById("program-health-label"),
  namespace: document.getElementById("program-page-namespace"),
  summary: document.getElementById("program-page-summary"),
  updated: document.getElementById("program-page-updated"),
  title: document.getElementById("program-page-title"),
  streamName: document.getElementById("program-page-stream-name"),
  sourceLabel: document.getElementById("program-page-source-label"),
  sourceNamespace: document.getElementById("program-page-source-namespace"),
  resolution: document.getElementById("program-page-resolution"),
  timeline: document.getElementById("program-page-timeline"),
  eventCount: document.getElementById("program-page-event-count"),
  overlay: document.getElementById("program-page-overlay"),
  status: document.getElementById("program-page-status"),
  watchSlot: document.getElementById("program-page-watch-slot"),
};

const player = {
  watchEl: null,
  currentStreamName: "",
  currentRouteKey: "",
  currentLatency: "real-time",
  reconnectAttempt: 0,
  nextReconnectAt: 0,
};

function getProgramRouteKey(program) {
  if (!program) return "";
  return [
    program.stream_id || "",
    program.source_namespace || "",
    program.effective_updated_at || program.updated_at || "",
  ].join("|");
}

function scheduleReconnect(playerRef, now, immediate = false) {
  const delay = immediate
    ? 0
    : PROGRAM_RECONNECT_DELAYS_MS[
      Math.min(playerRef.reconnectAttempt, PROGRAM_RECONNECT_DELAYS_MS.length - 1)
    ];
  playerRef.nextReconnectAt = now + delay;
}

function resetReconnectState(playerRef) {
  playerRef.reconnectAttempt = 0;
  playerRef.nextReconnectAt = 0;
}

function forceReconnect(playerRef) {
  if (!playerRef.currentStreamName) return;
  playerRef.watchEl = retuneWatch(
    refs.watchSlot,
    playerRef.watchEl,
    playerRef.currentStreamName,
    playerRef.currentLatency,
  );
}

function fmtTime(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderHealth(healthy, label) {
  refs.health.classList.toggle("healthy", healthy);
  refs.healthLabel.textContent = label;
}

function applySnapshot(snapshot) {
  state.program = snapshot.program || null;
  state.events = snapshot.events || [];
}

function syncPlayer() {
  const playback = state.program?.playback || null;
  const streamName = playback?.stream_name || "";
  const routeKey = getProgramRouteKey(state.program);

  refs.title.textContent = state.program?.source_label || "Waiting for route…";
  refs.streamName.textContent = streamName || "No stream";
  refs.sourceLabel.textContent = state.program?.source_label || "—";
  refs.sourceNamespace.textContent = state.program?.source_namespace || "—";

  if (!streamName) {
    refs.overlay.classList.remove("hidden");
    refs.status.textContent = "Waiting for route…";
    refs.resolution.textContent = "—";
    player.currentStreamName = "";
    player.currentRouteKey = "";
    resetReconnectState(player);
    return;
  }

  const streamChanged = player.currentStreamName !== streamName;
  const routeChanged = player.currentRouteKey !== routeKey;

  if (streamChanged || routeChanged) {
    player.currentLatency = playback.latency || playback.latency_ms || "real-time";
    player.watchEl = retuneWatch(
      refs.watchSlot,
      player.watchEl,
      streamName,
      player.currentLatency,
    );
    player.currentStreamName = streamName;
    player.currentRouteKey = routeKey;
    player.reconnectAttempt = 0;
    scheduleReconnect(player, performance.now());
    refs.overlay.classList.remove("hidden");
    refs.status.textContent = routeChanged && !streamChanged
      ? "Switching program source…"
      : `Connecting to ${streamName}…`;
    refs.resolution.textContent = "—";
  }
}

function renderSummary() {
  const program = state.program;
  if (!program) {
    refs.namespace.textContent = "lab/program/main";
    refs.summary.textContent = "Waiting for current route…";
    refs.updated.textContent = "No route changes yet.";
    return;
  }

  refs.namespace.textContent = program.output_namespace || "lab/program/main";
  if (program.modifier?.active && program.source_label) {
    refs.summary.textContent = `Subscribed to the stable ${program.output_stream_name || "stream_program"} output while ${program.source_label} overrides the routed source ${program.route_source_label || "—"}.`;
  } else if (program.source_label) {
    refs.summary.textContent = `Subscribed to the stable ${program.output_stream_name || "stream_program"} output while the current source is ${program.source_label}.`;
  } else {
    refs.summary.textContent = "Program route is set, but the source label is missing.";
  }
  refs.updated.textContent = `Last control change ${fmtTime(program.updated_at)}. Effective source ${program.source_namespace || "—"}.`;
}

function renderTimeline() {
  refs.eventCount.textContent = `${state.events.length} event${state.events.length === 1 ? "" : "s"}`;
  if (!state.events.length) {
    refs.timeline.innerHTML = `<div class="empty-state">No events yet.</div>`;
    return;
  }

  refs.timeline.innerHTML = [...state.events]
    .reverse()
    .slice(0, 20)
    .map((event) => `
      <article class="timeline-item">
        <div class="timeline-topline">
          <span class="timeline-type">${escapeHtml(event.type)}</span>
          <span>${fmtTime(event.timestamp)}</span>
        </div>
        <div class="timeline-message">${escapeHtml(event.message)}</div>
      </article>
    `)
    .join("");
}

function render() {
  renderSummary();
  renderTimeline();
  syncPlayer();
}

function startWatchPolling() {
  setInterval(() => {
    if (!player.currentStreamName) return;
    const now = performance.now();
    const stateRef = readWatchState(player.watchEl);
    if (stateRef.state === "live" && stateRef.hasFrame) {
      resetReconnectState(player);
      refs.overlay.classList.add("hidden");
      refs.status.textContent = "Playing live";
    } else if (stateRef.state === "buffering") {
      refs.overlay.classList.remove("hidden");
      refs.status.textContent = "Buffering…";
    } else {
      refs.overlay.classList.remove("hidden");
      refs.status.textContent = `Waiting for ${player.currentStreamName}…`;
    }
    refs.resolution.textContent = stateRef.resolution || "—";

    if (
      player.currentStreamName
      && player.nextReconnectAt
      && now >= player.nextReconnectAt
      && !(stateRef.state === "live" && stateRef.hasFrame)
    ) {
      forceReconnect(player);
      player.reconnectAttempt += 1;
      scheduleReconnect(player, now);
      refs.overlay.classList.remove("hidden");
      refs.status.textContent = `Reconnecting to ${player.currentStreamName}…`;
      refs.resolution.textContent = "—";
    }
  }, 500);
}

async function boot() {
  await ensureWatchReady();
  renderHealth(false, "Connecting…");
  try {
    const snapshot = await getRegistrySnapshot();
    applySnapshot(snapshot);
    renderHealth(true, "Registry live");
    render();
  } catch (error) {
    console.error(error);
    renderHealth(false, "Registry unavailable");
  }

  connectRegistryEvents({
    onSnapshot(snapshot) {
      applySnapshot(snapshot);
      renderHealth(true, "Registry live");
      render();
    },
    onError() {
      renderHealth(false, "Reconnecting…");
    },
  });

  startWatchPolling();
}

boot();

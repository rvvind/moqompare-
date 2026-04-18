import { connectRegistryEvents, getRegistrySnapshot, setProgramModifier, setProgramRoute } from "./api.js";
import { ensureWatchReady, readWatchState, retuneWatch } from "./watch.js";

const PROGRAM_RECONNECT_DELAYS_MS = [1200, 2400, 4000, 6500];

const state = {
  streams: [],
  program: null,
  selectedId: null,
  selectionPinned: false,
  events: [],
};

const refs = {
  catalogCount: document.getElementById("catalog-count"),
  catalogList: document.getElementById("catalog-list"),
  eventCount: document.getElementById("event-count"),
  timelineList: document.getElementById("timeline-list"),
  programNamespace: document.getElementById("program-namespace"),
  programSummary: document.getElementById("program-summary"),
  programUpdated: document.getElementById("program-updated"),
  selectionTitle: document.getElementById("selection-title"),
  selectionSummary: document.getElementById("selection-summary"),
  selectionNamespace: document.getElementById("selection-namespace"),
  selectionKind: document.getElementById("selection-kind"),
  selectionStatus: document.getElementById("selection-status"),
  selectionMediaReady: document.getElementById("selection-media-ready"),
  selectionTags: document.getElementById("selection-tags"),
  takeProgramBtn: document.getElementById("take-program-btn"),
  modifierTitle: document.getElementById("modifier-title"),
  modifierSummary: document.getElementById("modifier-summary"),
  takeSlateBtn: document.getElementById("take-slate-btn"),
  clearModifierBtn: document.getElementById("clear-modifier-btn"),
  registryHealth: document.getElementById("registry-health"),
  healthLabel: document.getElementById("health-label"),
  previewTitle: document.getElementById("preview-title"),
  previewStreamName: document.getElementById("preview-stream-name"),
  previewWatchSlot: document.getElementById("preview-watch-slot"),
  previewOverlay: document.getElementById("preview-overlay"),
  previewStatus: document.getElementById("preview-status"),
  previewResolution: document.getElementById("preview-resolution"),
  programTitle: document.getElementById("program-title"),
  programStreamName: document.getElementById("program-stream-name"),
  programWatchSlot: document.getElementById("program-watch-slot"),
  programOverlay: document.getElementById("program-overlay"),
  programStatus: document.getElementById("program-status"),
  programResolution: document.getElementById("program-resolution"),
};

const watchPlayers = {
  preview: {
    key: "preview",
    watchEl: null,
    currentStreamName: "",
    currentRouteKey: "",
    currentLatency: "real-time",
    reconnectAttempt: 0,
    nextReconnectAt: 0,
    autoReconnect: false,
    titleEl: refs.previewTitle,
    streamNameEl: refs.previewStreamName,
    slotEl: refs.previewWatchSlot,
    overlayEl: refs.previewOverlay,
    statusEl: refs.previewStatus,
    resolutionEl: refs.previewResolution,
    waitingText: "Select a source to preview…",
  },
  program: {
    key: "program",
    watchEl: null,
    currentStreamName: "",
    currentRouteKey: "",
    currentLatency: "real-time",
    reconnectAttempt: 0,
    nextReconnectAt: 0,
    autoReconnect: true,
    titleEl: refs.programTitle,
    streamNameEl: refs.programStreamName,
    slotEl: refs.programWatchSlot,
    overlayEl: refs.programOverlay,
    statusEl: refs.programStatus,
    resolutionEl: refs.programResolution,
    waitingText: "Waiting for program route…",
  },
};

refs.takeProgramBtn.addEventListener("click", () => {
  if (!state.selectedId) return;
  state.selectionPinned = true;
  takeToProgram(state.selectedId);
});

refs.takeSlateBtn.addEventListener("click", () => {
  applyProgramModifier("slate");
});

refs.clearModifierBtn.addEventListener("click", () => {
  applyProgramModifier(null);
});

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

function streamById(streamId) {
  return state.streams.find((stream) => stream.id === streamId) || null;
}

function enrichProgram(program) {
  if (!program) return null;

  const effectiveStream = program.stream || streamById(program.stream_id) || null;
  const routeStream = program.route_stream || streamById(program.route_stream_id || program.stream_id) || null;
  const modifierStreamId = program.modifier_stream?.id || program.modifier?.stream_id || null;
  const modifierStream = modifierStreamId
    ? streamById(modifierStreamId) || program.modifier_stream || null
    : null;

  return {
    ...program,
    stream: effectiveStream,
    source_label: program.source_label || effectiveStream?.label || null,
    source_namespace: program.source_namespace || effectiveStream?.namespace || null,
    source_playback: program.source_playback || effectiveStream?.playback || null,
    source_republish: program.source_republish || effectiveStream?.republish || null,
    route_stream: routeStream,
    route_source_label: program.route_source_label || routeStream?.label || null,
    route_source_namespace: program.route_source_namespace || routeStream?.namespace || null,
    route_source_playback: program.route_source_playback || routeStream?.playback || null,
    route_source_republish: program.route_source_republish || routeStream?.republish || null,
    modifier_stream: modifierStream,
    modifier_label: program.modifier_label || modifierStream?.label || program.modifier?.label || null,
  };
}

function ensureSelectedStream() {
  const programId = state.program?.route_stream_id || state.program?.stream_id;
  const programStream = programId ? streamById(programId) : null;
  const selectedStream = state.selectedId ? streamById(state.selectedId) : null;

  if (state.selectionPinned && selectedStream) {
    return;
  }

  if (programStream) {
    state.selectedId = programId;
    return;
  }

  if (selectedStream) {
    return;
  }

  state.selectedId = state.streams[0]?.id || null;
}

function getPlayback(stream) {
  return stream?.playback || null;
}

function getProgramPlaybackTarget() {
  if (!state.program?.playback) return null;
  return {
    label: state.program.source_label || state.program?.stream?.label || "Program Output",
    playback: state.program.playback,
    routeKey: [
      state.program.stream_id || "",
      state.program.source_namespace || "",
      state.program.effective_updated_at || state.program.updated_at || "",
    ].join("|"),
  };
}

function scheduleReconnect(player, now) {
  const delay = PROGRAM_RECONNECT_DELAYS_MS[
    Math.min(player.reconnectAttempt, PROGRAM_RECONNECT_DELAYS_MS.length - 1)
  ];
  player.nextReconnectAt = now + delay;
}

function resetReconnectState(player) {
  player.reconnectAttempt = 0;
  player.nextReconnectAt = 0;
}

function forceReconnect(player) {
  if (!player.currentStreamName) return;
  player.watchEl = retuneWatch(
    player.slotEl,
    player.watchEl,
    player.currentStreamName,
    player.currentLatency,
  );
}

function resetPlayer(player, title, message, streamLabel = "No stream") {
  player.titleEl.textContent = title;
  player.streamNameEl.textContent = streamLabel;
  player.statusEl.textContent = message;
  player.overlayEl.classList.remove("hidden");
  player.resolutionEl.textContent = "—";
  player.currentRouteKey = "";
  resetReconnectState(player);
}

function syncPlayer(player, stream, titleFallback) {
  const playback = getPlayback(stream);
  const routeKey = stream?.routeKey || "";
  if (!stream || !playback?.stream_name) {
    resetPlayer(player, titleFallback, player.waitingText);
    player.currentStreamName = "";
    return;
  }

  const streamName = playback.stream_name;
  const title = stream.label || titleFallback;
  player.titleEl.textContent = title;
  player.streamNameEl.textContent = streamName;

  const streamChanged = player.currentStreamName !== streamName;
  const routeChanged = player.currentRouteKey !== routeKey;

  if (streamChanged || routeChanged) {
    player.currentLatency = playback.latency || playback.latency_ms || "real-time";
    player.watchEl = retuneWatch(
      player.slotEl,
      player.watchEl,
      streamName,
      player.currentLatency,
    );
    player.currentStreamName = streamName;
    player.currentRouteKey = routeKey;
    player.reconnectAttempt = 0;
    if (player.autoReconnect) {
      scheduleReconnect(player, performance.now());
    } else {
      player.nextReconnectAt = 0;
    }
    player.statusEl.textContent = routeChanged && !streamChanged
      ? "Switching program source…"
      : `Connecting to ${streamName}…`;
    player.overlayEl.classList.remove("hidden");
    player.resolutionEl.textContent = "—";
  }
}

function renderCatalog() {
  refs.catalogCount.textContent = `${state.streams.length} stream${state.streams.length === 1 ? "" : "s"}`;

  if (!state.streams.length) {
    refs.catalogList.innerHTML = `<div class="empty-state">No streams in catalog yet.</div>`;
    return;
  }

  refs.catalogList.innerHTML = state.streams.map((stream) => {
    const selected = stream.id === state.selectedId;
    const playback = getPlayback(stream);
    return `
      <article class="catalog-item${selected ? " is-selected" : ""}" data-stream-id="${escapeHtml(stream.id)}">
        <div class="catalog-topline">
          <div class="catalog-title">${escapeHtml(stream.label)}</div>
          <span class="status-chip status-${escapeHtml(stream.status)}">${escapeHtml(stream.status)}</span>
        </div>
        <div class="catalog-summary">${escapeHtml(stream.summary || "No summary yet.")}</div>
        <div class="catalog-meta">
          <code>${escapeHtml(stream.namespace)}</code>
          <span class="meta-token">${escapeHtml(stream.kind)}</span>
          <span class="meta-token">${stream.media_ready ? "media ready" : "conditional media"}</span>
          ${playback?.stream_name ? `<span class="meta-token">${escapeHtml(playback.stream_name)}</span>` : ""}
        </div>
        <div class="tag-row">
          ${(stream.tags || []).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}
        </div>
        <div class="action-row">
          <button class="secondary-btn" type="button" data-action="inspect" data-stream-id="${escapeHtml(stream.id)}">Preview</button>
          <button class="primary-btn" type="button" data-action="take" data-stream-id="${escapeHtml(stream.id)}">Take to Program</button>
        </div>
      </article>
    `;
  }).join("");

  refs.catalogList.querySelectorAll("[data-action='inspect']").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.selectedId = btn.dataset.streamId;
      state.selectionPinned = true;
      render();
    });
  });

  refs.catalogList.querySelectorAll("[data-action='take']").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.selectedId = btn.dataset.streamId;
      state.selectionPinned = true;
      render();
      takeToProgram(btn.dataset.streamId);
    });
  });
}

function renderProgramSummary() {
  const program = state.program;
  if (!program) {
    refs.programNamespace.textContent = "lab/program/main";
    refs.programSummary.textContent = "Waiting for current route…";
    refs.programUpdated.textContent = "No program route yet.";
    return;
  }

  refs.programNamespace.textContent = program.output_namespace || "lab/program/main";
  if (program.modifier?.active && program.stream) {
    refs.programSummary.textContent = `${program.stream.label} is overriding the routed source ${program.route_source_label || "—"} on the stable program monitor.`;
  } else if (program.route_stream) {
    refs.programSummary.textContent = `${program.route_stream.label} currently feeds the route-following program monitor.`;
  } else {
    refs.programSummary.textContent = "Program route is set, but the source metadata is missing.";
  }
  refs.programUpdated.textContent = `Last control change ${fmtTime(program.updated_at)}. Effective source ${program.source_namespace || "—"}.`;
}

function renderModifierCard() {
  const program = state.program;
  const slateStream = streamById("slate");
  const active = Boolean(program?.modifier?.active);

  refs.takeSlateBtn.disabled = !slateStream || active;
  refs.clearModifierBtn.disabled = !active;

  if (!active) {
    refs.modifierTitle.textContent = "No modifier active";
    refs.modifierSummary.textContent = program?.route_source_label
      ? `${program.route_source_label} is feeding program directly. Use Take Slate to override it temporarily.`
      : "Program currently follows the routed source directly.";
    return;
  }

  refs.modifierTitle.textContent = `${program.modifier_label || "Modifier"} active`;
  refs.modifierSummary.textContent = `${program.modifier_label || "The modifier"} is overriding ${program.route_source_label || "the routed source"} while downstream viewers stay on ${program.output_stream_name || "stream_program"}.`;
}

function renderSelection() {
  const stream = streamById(state.selectedId);
  refs.takeProgramBtn.disabled = !stream;

  if (!stream) {
    refs.selectionTitle.textContent = "Choose a source from the catalog";
    refs.selectionSummary.textContent = "Use Preview in the discovery column to confirm the source before taking it to program.";
    refs.selectionNamespace.textContent = "—";
    refs.selectionKind.textContent = "—";
    refs.selectionStatus.textContent = "—";
    refs.selectionMediaReady.textContent = "—";
    refs.selectionTags.innerHTML = "";
    return;
  }

  refs.selectionTitle.textContent = stream.label;
  refs.selectionSummary.textContent = stream.summary || "No summary yet.";
  refs.selectionNamespace.textContent = stream.namespace;
  refs.selectionKind.textContent = stream.kind;
  refs.selectionStatus.textContent = stream.status;
  refs.selectionMediaReady.textContent = stream.media_ready ? "yes" : "conditional";
  refs.selectionTags.innerHTML = (stream.tags || [])
    .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
    .join("");
}

function renderTimeline() {
  refs.eventCount.textContent = `${state.events.length} event${state.events.length === 1 ? "" : "s"}`;
  if (!state.events.length) {
    refs.timelineList.innerHTML = `<div class="empty-state">No events yet. Route a source to program to create the first operator action.</div>`;
    return;
  }

  refs.timelineList.innerHTML = [...state.events]
    .reverse()
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

function renderHealth(healthy, label) {
  refs.registryHealth.classList.toggle("healthy", healthy);
  refs.healthLabel.textContent = label;
}

function updatePlayerTargets() {
  const selectedStream = streamById(state.selectedId);
  syncPlayer(watchPlayers.preview, selectedStream, "Catalog Preview");
  syncPlayer(watchPlayers.program, getProgramPlaybackTarget(), "Program Monitor");
}

function render() {
  state.program = enrichProgram(state.program);
  ensureSelectedStream();
  renderCatalog();
  renderProgramSummary();
  renderSelection();
  renderModifierCard();
  renderTimeline();
  updatePlayerTargets();
}

function applySnapshot(snapshot) {
  state.streams = snapshot.streams || [];
  state.program = enrichProgram(snapshot.program || null);
  state.events = snapshot.events || [];
}

async function fetchSnapshot() {
  const snapshot = await getRegistrySnapshot();
  applySnapshot(snapshot);
  renderHealth(true, "Registry live");
  render();
}

async function takeToProgram(streamId) {
  refs.takeProgramBtn.disabled = true;
  try {
    const payload = await setProgramRoute(streamId);
    if (payload.program) {
      state.program = enrichProgram({
        ...payload.program,
        route_stream: payload.route_stream || streamById(payload.program.route_stream_id) || streamById(streamId) || null,
        stream: payload.stream || streamById(payload.program.stream_id) || null,
      });
    }
    renderHealth(true, "Route applied");
    render();
  } catch (error) {
    console.error(error);
    renderHealth(false, "Route update failed");
  } finally {
    refs.takeProgramBtn.disabled = false;
  }
}

async function applyProgramModifier(streamId) {
  refs.takeSlateBtn.disabled = true;
  refs.clearModifierBtn.disabled = true;
  try {
    const payload = await setProgramModifier(streamId);
    if (payload.program) {
      state.program = enrichProgram({
        ...payload.program,
        route_stream: payload.route_stream || streamById(payload.program.route_stream_id) || null,
        stream: payload.stream || streamById(payload.program.stream_id) || null,
      });
    }
    renderHealth(true, streamId ? "Modifier applied" : "Modifier cleared");
    render();
  } catch (error) {
    console.error(error);
    renderHealth(false, "Modifier update failed");
  }
}

function startWatchPolling() {
  setInterval(() => {
    Object.values(watchPlayers).forEach((player) => {
      if (!player.currentStreamName) return;
      const now = performance.now();
      const stateRef = readWatchState(player.watchEl);

      if (stateRef.state === "live" && stateRef.hasFrame) {
        resetReconnectState(player);
        player.overlayEl.classList.add("hidden");
        player.statusEl.textContent = "Playing live";
      } else if (stateRef.state === "buffering") {
        player.overlayEl.classList.remove("hidden");
        player.statusEl.textContent = "Buffering…";
      } else {
        player.overlayEl.classList.remove("hidden");
        player.statusEl.textContent = `Waiting for ${player.currentStreamName}…`;
      }

      player.resolutionEl.textContent = stateRef.resolution || "—";

      if (
        player.autoReconnect
        && player.nextReconnectAt
        && now >= player.nextReconnectAt
        && !(stateRef.state === "live" && stateRef.hasFrame)
      ) {
        forceReconnect(player);
        player.reconnectAttempt += 1;
        scheduleReconnect(player, now);
        player.overlayEl.classList.remove("hidden");
        player.statusEl.textContent = `Reconnecting to ${player.currentStreamName}…`;
        player.resolutionEl.textContent = "—";
      }
    });
  }, 500);
}

async function boot() {
  await ensureWatchReady();
  renderHealth(false, "Connecting…");
  try {
    await fetchSnapshot();
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

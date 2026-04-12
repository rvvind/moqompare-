import {
  applyImpairment,
  connectPresentationEvents,
  formatBitrate,
  formatMilliseconds,
  formatSeconds,
  getImpairmentStatus,
  getPresentationSnapshot,
  impairmentTone,
  metricTone,
  pushPresentationTelemetry,
  setPresentationState,
} from "./api.js";
import {
  PRESENTATION_SCENES,
  buildSceneState,
  getAdjacentScene,
  getScene,
  getSceneIndex,
} from "./scenes.js";

const BITRATE_WINDOW_SIZE = 8;

const stateRef = {
  state: null,
  telemetry: null,
  driftSeconds: null,
  hlsLevel: null,
  hlsLevelCount: 0,
};

const protocolRefs = {
  hls: {
    protocol: "hls",
    videoSurface: document.getElementById("hls-video"),
    overlay: document.getElementById("hls-overlay"),
    status: document.getElementById("hls-status"),
    summary: document.getElementById("hls-summary"),
    metrics: {
      startup: { el: null, value: null },
      liveLatency: { el: document.getElementById("hls-liveLatency"), value: null },
      stallCount: { el: document.getElementById("hls-stallCount"), value: 0 },
      bitrate: { el: document.getElementById("hls-bitrate"), value: null },
    },
    detailEl: document.getElementById("hls-bitrate-meta"),
    playbackState: "connecting",
    startupMs: null,
    liveLatency: null,
    stallCount: 0,
    bitrate: null,
    bitrateHistory: [],
    resolution: null,
    streamName: "manifest-driven",
  },
  moq: {
    protocol: "moq",
    videoSurface: document.getElementById("moq-watch"),
    overlay: document.getElementById("moq-overlay"),
    status: document.getElementById("moq-status"),
    summary: document.getElementById("moq-summary"),
    metrics: {
      startup: { el: null, value: null },
      liveLatency: { el: document.getElementById("moq-liveLatency"), value: null },
      stallCount: { el: document.getElementById("moq-stallCount"), value: 0 },
      bitrate: { el: document.getElementById("moq-bitrate"), value: null },
    },
    detailEl: document.getElementById("moq-bitrate-meta"),
    playbackState: "connecting",
    startupMs: null,
    liveLatency: 2,
    stallCount: 0,
    bitrate: null,
    bitrateHistory: [],
    resolution: null,
    streamName: "stream_hi",
  },
};

const storyRefs = {
  headline: document.getElementById("story-headline"),
  subhead: document.getElementById("story-subhead"),
  impairment: document.getElementById("impairment-pill"),
  sharedStartup: document.getElementById("shared-startup"),
  sharedDrift: document.getElementById("shared-drift"),
  sharedDriftMeta: document.getElementById("shared-drift-meta"),
  sharedCondition: document.getElementById("shared-condition"),
  sharedConditionMeta: document.getElementById("shared-condition-meta"),
  calloutEyebrow: document.getElementById("callout-eyebrow"),
  calloutTitle: document.getElementById("callout-title"),
  calloutBody: document.getElementById("callout-body"),
};

const presenterRefs = {
  toggle: document.getElementById("present-toggle"),
  rail: document.getElementById("present-rail"),
  backdrop: document.getElementById("present-backdrop"),
  videoComparison: document.getElementById("video-comparison"),
  videoSizeToggle: document.getElementById("video-size-toggle"),
  videoSizeToggleLabel: document.getElementById("video-size-toggle-label"),
  pin: document.getElementById("present-pin"),
  pinLabel: document.getElementById("present-pin-label"),
  close: document.getElementById("present-close"),
  sceneItems: document.getElementById("scene-items"),
  scenePosition: document.getElementById("scene-position"),
  sceneCurrentTitle: document.getElementById("scene-current-title"),
  contextPanel: document.getElementById("context-panel"),
  headline: document.getElementById("console-headline"),
  subhead: document.getElementById("console-subhead"),
  impairment: document.getElementById("console-impairment"),
  audienceStatus: document.getElementById("audience-status"),
  audienceTelemetry: document.getElementById("audience-telemetry"),
  healthPanel: document.getElementById("health-panel"),
  sceneControls: document.querySelector(".scene-controls-panel"),
  sceneControlsIndicator: document.getElementById("scene-controls-indicator"),
  prevScene: document.getElementById("prev-scene"),
  nextScene: document.getElementById("next-scene"),
  resetBaseline: document.getElementById("reset-baseline"),
  applyRecommended: document.getElementById("apply-recommended"),
};

const presenterShellState = {
  open: false,
  pinned: false,
};

const stageNodes = Array.from(document.querySelectorAll("[data-node]"));
const stageEdges = Array.from(document.querySelectorAll("[data-edge]"));
const metricTiles = Array.from(document.querySelectorAll(".metric-tile"));
const stageMap = document.querySelector(".stage-map");

// ── Stage map: dynamic SVG path routing ──────────────────────────────────────
// Replaces hardcoded viewBox coordinates with values derived from actual
// rendered node bounding rects, so arrows connect at box edges regardless
// of container size or node height.
function updateStagePaths() {
  if (!stageMap) return;
  const mapRect = stageMap.getBoundingClientRect();
  if (mapRect.width === 0 || mapRect.height === 0) return;

  const VW = 1000;
  const VH = 780;

  function toSvg(clientX, clientY) {
    return [
      Math.round(((clientX - mapRect.left) / mapRect.width) * VW),
      Math.round(((clientY - mapRect.top) / mapRect.height) * VH),
    ];
  }

  function nodePoint(nodeId, side) {
    const el = stageMap.querySelector(`[data-node="${nodeId}"]`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    switch (side) {
      case "top":       return toSvg(r.left + r.width * 0.5, r.top);
      case "bottom":    return toSvg(r.left + r.width * 0.5, r.bottom);
      case "bottom-30": return toSvg(r.left + r.width * 0.3, r.bottom);
      case "bottom-70": return toSvg(r.left + r.width * 0.7, r.bottom);
      case "right":     return toSvg(r.right, r.top + r.height * 0.5);
      default:          return null;
    }
  }

  const pathDefs = {
    "source-packager": () => {
      const from = nodePoint("source", "bottom");
      const to   = nodePoint("packager", "top");
      if (!from || !to) return null;
      return `M${from[0]} ${from[1]} L${to[0]} ${to[1]}`;
    },
    "hls-origin": () => {
      const from = nodePoint("packager", "bottom-30");
      const to   = nodePoint("origin", "top");
      if (!from || !to) return null;
      const my = Math.round((from[1] + to[1]) / 2);
      return `M${from[0]} ${from[1]} C${from[0]} ${my} ${to[0]} ${my} ${to[0]} ${to[1]}`;
    },
    "hls-manifest": () => {
      const from = nodePoint("origin", "bottom");
      const to   = nodePoint("manifest-proxy", "top");
      if (!from || !to) return null;
      return `M${from[0]} ${from[1]} L${to[0]} ${to[1]}`;
    },
    "hls-delivery": () => {
      const from = nodePoint("manifest-proxy", "bottom");
      const to   = nodePoint("viewer-hls", "top");
      if (!from || !to) return null;
      return `M${from[0]} ${from[1]} L${to[0]} ${to[1]}`;
    },
    "hls-poll": () => {
      const from = nodePoint("viewer-hls", "right");
      const to   = nodePoint("manifest-proxy", "right");
      if (!from || !to) return null;
      const loopX = Math.round(Math.max(from[0], to[0]) + 55);
      return `M${from[0]} ${from[1]} C${loopX} ${from[1]} ${loopX} ${to[1]} ${to[0]} ${to[1]}`;
    },
    "moq-publish": () => {
      const from = nodePoint("packager", "bottom-70");
      const to   = nodePoint("publisher", "top");
      if (!from || !to) return null;
      const my = Math.round((from[1] + to[1]) / 2);
      return `M${from[0]} ${from[1]} C${from[0]} ${my} ${to[0]} ${my} ${to[0]} ${to[1]}`;
    },
    "moq-relay": () => {
      const from = nodePoint("publisher", "bottom");
      const to   = nodePoint("relay", "top");
      if (!from || !to) return null;
      return `M${from[0]} ${from[1]} L${to[0]} ${to[1]}`;
    },
    "moq-delivery": () => {
      const from = nodePoint("relay", "bottom");
      const to   = nodePoint("viewer-moq", "top");
      if (!from || !to) return null;
      return `M${from[0]} ${from[1]} L${to[0]} ${to[1]}`;
    },
  };

  for (const edge of stageEdges) {
    const fn = pathDefs[edge.dataset.edge];
    if (!fn) continue;
    const d = fn();
    if (d) edge.setAttribute("d", d);
  }
}
const impairmentButtons = Array.from(document.querySelectorAll("[data-impairment]"));
const PRESENTER_PIN_STORAGE_KEY = "moqompare.presentation.railPinned";
const PRESENTATION_VIDEO_COMPACT_STORAGE_KEY = "moqompare.presentation.videoCompact";
const IMPAIRMENT_CONTEXT = [
  {
    id: "baseline",
    label: "Baseline",
    tone: "good",
    summary: "No impairment. This is the clean reference state before delivery is stressed.",
    hls: "HLS polls fresh manifests and fetches segments over HTTP without any induced loss, freeze, or bandwidth pressure.",
    moq: "MoQ receives newly published objects through the relay without any induced loss, freeze, or bandwidth pressure.",
  },
  {
    id: "jitter",
    label: "Jitter + Loss",
    tone: "warn",
    summary: "Adds delay variation and packet loss without fully taking delivery down.",
    hls: "TCP congestion control halves its window on every lost packet. At 1% loss with 30 ms RTT, effective throughput falls to roughly the high-rendition ceiling, so hls.js often drops to the low rendition.",
    moq: "QUIC recovers loss through retransmission without the same throughput collapse. The MoQ ABR logic is jitter-aware and only switches down if MoQ itself is stalling and bandwidth is low.",
  },
  {
    id: "squeeze",
    label: "Bandwidth Squeeze",
    tone: "warn",
    summary: "Caps delivery capacity so both paths have to adapt to a constrained link.",
    hls: "A 500 kbps cap starves TCP. hls.js sees the reduced throughput and switches to the low rendition at 640x360 and 500 kbps.",
    moq: "The MoQ controller reads hls.js bandwidth estimates. Once measured bandwidth stays below 3.6 Mbps, it switches from stream_hi to stream_lo; it returns to high only after bandwidth rises above 5.2 Mbps.",
  },
  {
    id: "outage",
    label: "Burst Outage",
    tone: "bad",
    summary: "Temporarily removes delivery to expose each protocol's recovery path.",
    hls: "100% loss stalls TCP, drains the player buffer, and forces hls.js to re-buffer once the path comes back after five seconds.",
    moq: "QUIC idle timeout closes the WebTransport session and the player reconnects automatically. Recovery is typically faster because QUIC can re-establish in one RTT, with 0-RTT on retry.",
  },
  {
    id: "stale_manifest",
    label: "Stale Manifest",
    tone: "bad",
    summary: "Freezes only the HLS control loop while leaving segment delivery and MoQ publication healthy.",
    hls: "The player polls the manifest about every two seconds. When the manifest is frozen, it keeps seeing the same stale segment list and stalls even though bandwidth and the segment server are healthy. This auto-clears after 30 seconds.",
    moq: "MoQ is manifest-less. The relay keeps pushing fresh media objects as they are packaged, so there is nothing to poll and nothing to freeze.",
  },
];

function setText(el, text) {
  if (el) el.textContent = text;
}

function setHTML(el, html) {
  if (el) el.innerHTML = html;
}

function setTone(el, tone) {
  if (!el) return;
  el.classList.remove("tone-good", "tone-warn", "tone-bad", "tone-muted");
  el.classList.add(`tone-${tone}`);
}

function setRailOpen(isOpen) {
  presenterShellState.open = isOpen || presenterShellState.pinned;
  document.body.classList.toggle("is-rail-open", presenterShellState.open);
  presenterRefs.toggle?.setAttribute("aria-expanded", presenterShellState.open ? "true" : "false");
  presenterRefs.rail?.setAttribute("aria-hidden", presenterShellState.open ? "false" : "true");
  if (presenterRefs.backdrop) {
    presenterRefs.backdrop.hidden = !presenterShellState.open || presenterShellState.pinned;
  }
}

function setRailPinned(isPinned) {
  presenterShellState.pinned = isPinned;
  document.body.classList.toggle("is-rail-pinned", isPinned);
  presenterRefs.pin?.setAttribute("aria-pressed", isPinned ? "true" : "false");
  if (presenterRefs.pinLabel) {
    presenterRefs.pinLabel.textContent = isPinned ? "Unpin Sidebar" : "Pin Sidebar";
  }
  try {
    window.localStorage.setItem(PRESENTER_PIN_STORAGE_KEY, isPinned ? "1" : "0");
  } catch {
    // best effort only
  }
  setRailOpen(isPinned || presenterShellState.open);
}

function setVideoCompact(isCompact) {
  document.body.classList.toggle("is-video-compact", isCompact);
  presenterRefs.videoSizeToggle?.setAttribute("aria-pressed", isCompact ? "true" : "false");
  if (presenterRefs.videoSizeToggleLabel) {
    presenterRefs.videoSizeToggleLabel.textContent = isCompact ? "Expand Players" : "Compact Players";
  }
  try {
    window.localStorage.setItem(PRESENTATION_VIDEO_COMPACT_STORAGE_KEY, isCompact ? "1" : "0");
  } catch {
    // best effort only
  }
}

function initializePresenterShell() {
  try {
    presenterShellState.pinned = window.localStorage.getItem(PRESENTER_PIN_STORAGE_KEY) === "1";
  } catch {
    presenterShellState.pinned = false;
  }

  setRailPinned(presenterShellState.pinned);
  if (!presenterShellState.pinned) {
    setRailOpen(false);
  }

  try {
    setVideoCompact(window.localStorage.getItem(PRESENTATION_VIDEO_COMPACT_STORAGE_KEY) === "1");
  } catch {
    setVideoCompact(false);
  }

  presenterRefs.toggle?.addEventListener("click", () => {
    if (presenterShellState.pinned) {
      setRailPinned(false);
      return;
    }
    setRailOpen(!presenterShellState.open);
  });

  presenterRefs.close?.addEventListener("click", () => {
    if (!presenterShellState.pinned) {
      setRailOpen(false);
    }
  });

  presenterRefs.pin?.addEventListener("click", () => {
    setRailPinned(!presenterShellState.pinned);
  });

  presenterRefs.videoSizeToggle?.addEventListener("click", () => {
    const nextCompact = !document.body.classList.contains("is-video-compact");
    setVideoCompact(nextCompact);
  });

  presenterRefs.backdrop?.addEventListener("click", () => {
    if (!presenterShellState.pinned) {
      setRailOpen(false);
    }
  });

  document.addEventListener("pointerdown", (event) => {
    if (!presenterShellState.open || presenterShellState.pinned) return;
    const target = event.target;
    if (!(target instanceof Node)) return;
    if (presenterRefs.rail?.contains(target) || presenterRefs.toggle?.contains(target)) return;
    setRailOpen(false);
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && presenterShellState.open && !presenterShellState.pinned) {
      setRailOpen(false);
    }
  });
}

function currentScene() {
  return getScene(stateRef.state?.sceneId || "opening");
}

function currentImpairment() {
  return stateRef.state?.activeImpairment || "baseline";
}

function driftSeconds() {
  if (typeof stateRef.driftSeconds === "number") return stateRef.driftSeconds;
  return deriveFallbackDriftSeconds();
}

function recordBitrateSample(protocol, sampleBps) {
  if (typeof sampleBps !== "number" || Number.isNaN(sampleBps) || sampleBps <= 0) return;
  const ref = protocolRefs[protocol];
  ref.bitrateHistory.push(sampleBps);
  if (ref.bitrateHistory.length > BITRATE_WINDOW_SIZE) {
    ref.bitrateHistory.shift();
  }
  ref.bitrate =
    ref.bitrateHistory.reduce((sum, value) => sum + value, 0) / ref.bitrateHistory.length;
}

function updateMetricTile(protocol, metricName, value, formatter, toneKey = metricName) {
  const tile = document.querySelector(
    `.metric-tile[data-protocol="${protocol}"][data-metric="${metricName}"]`,
  );
  const protocolRef = protocolRefs[protocol];
  const metricRef = protocolRef.metrics[metricName];
  metricRef.value = value;
  if (metricRef.el) {
    metricRef.el.textContent = formatter(value);
    setTone(metricRef.el, metricTone(toneKey, value));
  }
  if (tile) {
    tile.dataset.tone = metricTone(toneKey, value);
  }
}

function updateProtocolSummary(protocol, text) {
  setText(protocolRefs[protocol].summary, text);
}

function detailTone(playbackState) {
  if (playbackState === "playing") return "good";
  if (playbackState === "buffering") return "warn";
  if (playbackState === "unsupported" || playbackState === "error") return "bad";
  return "muted";
}

function toneSpan(text, tone = "muted") {
  return `<span class="tone-${tone}">${text}</span>`;
}

function pairValue(label, value, tone = "muted") {
  return `${toneSpan(label, "muted")} ${toneSpan(value, tone)}`;
}

function detailRow(key, valueHtml) {
  return `
    <div class="detail-row">
      <span class="key">${key}</span>
      <span class="val">${valueHtml}</span>
    </div>
  `;
}

function renderSharedTelemetry() {
  const hls = protocolRefs.hls;
  const moq = protocolRefs.moq;
  const startup = [
    hls.startupMs !== null
      ? toneSpan(`HLS ${formatMilliseconds(hls.startupMs)}`, metricTone("startup", hls.startupMs))
      : null,
    moq.startupMs !== null
      ? toneSpan(`MoQ ${formatMilliseconds(moq.startupMs)}`, metricTone("startup", moq.startupMs))
      : null,
  ]
    .filter(Boolean)
    .join(" | ");

  setHTML(storyRefs.sharedStartup, startup || "measuring…");
  setTone(storyRefs.sharedStartup, startup ? "good" : "muted");

  const drift = driftSeconds();
  if (typeof drift === "number") {
    setText(storyRefs.sharedDrift, formatSeconds(Math.abs(drift)));
    setTone(storyRefs.sharedDrift, metricTone("drift", Math.abs(drift)));
    setText(
      storyRefs.sharedDriftMeta,
      drift >= 0
        ? `HLS trails MoQ by ${formatSeconds(drift)}.`
        : `MoQ trails HLS by ${formatSeconds(Math.abs(drift))}.`,
    );
  } else {
    setText(storyRefs.sharedDrift, "measuring…");
    setText(storyRefs.sharedDriftMeta, "Comparing how far apart the experiences appear on screen.");
    setTone(storyRefs.sharedDrift, "muted");
  }

  const impairment = currentImpairment();
  setText(storyRefs.sharedCondition, impairment.replaceAll("_", " "));
  setText(
    storyRefs.sharedConditionMeta,
    impairment === "baseline"
      ? "The source remains healthy while delivery conditions change."
      : `The presenter is stressing the ${impairment.replaceAll("_", " ")} path right now.`,
  );
  setTone(storyRefs.sharedCondition, impairmentTone(impairment));

  renderPresenterTelemetry();
}

function deriveFallbackDriftSeconds() {
  if (
    typeof protocolRefs.hls.liveLatency === "number" &&
    typeof protocolRefs.moq.liveLatency === "number"
  ) {
    return protocolRefs.hls.liveLatency - protocolRefs.moq.liveLatency;
  }
  return null;
}

function impairmentTargets(profile) {
  switch (profile) {
    case "stale_manifest":
      return {
        nodes: ["manifest-proxy", "viewer-hls"],
        edges: ["hls-manifest", "hls-poll"],
      };
    case "jitter":
    case "squeeze":
    case "outage":
      return {
        nodes: ["viewer-hls", "viewer-moq", "manifest-proxy", "relay"],
        edges: ["hls-delivery", "moq-delivery"],
      };
    default:
      return { nodes: [], edges: [] };
  }
}

function applyStageState() {
  const scene = currentScene();
  const spotlightNodes = new Set(scene.spotlight?.nodes || []);
  const spotlightEdges = new Set(scene.spotlight?.edges || []);
  const impairmentHighlight = impairmentTargets(currentImpairment());

  stageNodes.forEach((node) => {
    const id = node.dataset.node;
    node.classList.toggle("is-spotlit", spotlightNodes.has(id));
    node.classList.toggle("is-dimmed", !spotlightNodes.has(id));
    node.classList.toggle("is-impaired", impairmentHighlight.nodes.includes(id));
  });

  stageEdges.forEach((edge) => {
    const id = edge.dataset.edge;
    edge.classList.toggle("is-spotlit", spotlightEdges.has(id));
    edge.classList.toggle("is-dimmed", !spotlightEdges.has(id));
    edge.classList.toggle("is-impaired", impairmentHighlight.edges.includes(id));
  });

  setText(storyRefs.calloutEyebrow, scene.title);
  setText(storyRefs.calloutTitle, scene.overlay.title);
  setText(storyRefs.calloutBody, scene.overlay.body);
  setTone(storyRefs.calloutEyebrow, scene.overlay.tone || "good");

  metricTiles.forEach((tile) => tile.classList.remove("is-promoted"));
  (scene.promotedMetrics || []).forEach((metricName) => {
    document
      .querySelectorAll(`.metric-tile[data-metric="${metricName}"]`)
      .forEach((tile) => tile.classList.add("is-promoted"));
  });

  if (scene.focus === "hls") {
    updateProtocolSummary("hls", "Polling manifests and fetching the next segment.");
    updateProtocolSummary("moq", "Reference path for comparison while HLS is in focus.");
  } else if (scene.focus === "moq") {
    updateProtocolSummary("hls", "Reference path for comparison while MoQ is in focus.");
    updateProtocolSummary("moq", "Publishing fresh media objects through the relay.");
  } else if (scene.focus === "stale-manifest") {
    updateProtocolSummary("hls", "Waiting on a manifest that is no longer advancing.");
    updateProtocolSummary("moq", "Still receiving fresh media objects through the relay.");
  } else {
    updateProtocolSummary("hls", "Polling manifests and fetching the next segment.");
    updateProtocolSummary("moq", "Publishing fresh media objects through the relay.");
  }
}

function syncImpairmentButtons() {
  const activeProfile = currentImpairment();
  impairmentButtons.forEach((button) => {
    const active = button.dataset.impairment === activeProfile;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function renderSceneList() {
  if (!presenterRefs.sceneItems) return;
  const scene = currentScene();
  presenterRefs.sceneItems.innerHTML = "";
  PRESENTATION_SCENES.forEach((item) => {
    const button = document.createElement("button");
    button.className = `scene-item${item.id === scene.id ? " active" : ""}`;
    button.type = "button";
    button.innerHTML = `
      <div class="title">${item.title}</div>
      <div class="copy">${item.subhead}</div>
    `;
    button.addEventListener("click", () => {
      applyScene(item.id).catch((error) => console.error(error));
    });
    presenterRefs.sceneItems.appendChild(button);
  });
}

function renderContext() {
  if (!presenterRefs.contextPanel) return;
  const activeImpairment = currentImpairment();
  const item =
    IMPAIRMENT_CONTEXT.find((entry) => entry.id === activeImpairment) || IMPAIRMENT_CONTEXT[0];
  presenterRefs.contextPanel.innerHTML = `
    <article class="context-item active">
      <div class="context-item-head">
        <div>
          <div class="context-item-title">${item.label}</div>
          <div class="context-item-summary">${item.summary}</div>
        </div>
        <span class="impairment-pill tone-${item.tone}">${item.id.replaceAll("_", " ")}</span>
      </div>
      <div class="context-protocol-grid">
        <div class="context-protocol-copy">
          <div class="context-protocol-label">HLS</div>
          <p>${item.hls}</p>
        </div>
        <div class="context-protocol-copy">
          <div class="context-protocol-label">MoQ</div>
          <p>${item.moq}</p>
        </div>
      </div>
    </article>
  `;
}

function renderSceneDetails() {
  const scene = currentScene();
  const index = Math.max(0, getSceneIndex(scene.id));
  setText(presenterRefs.scenePosition, `${index + 1} / ${PRESENTATION_SCENES.length}`);
  setText(presenterRefs.sceneCurrentTitle, scene.title);
  setText(presenterRefs.headline, stateRef.state?.headline || scene.headline);
  setText(presenterRefs.subhead, stateRef.state?.subhead || scene.subhead);

  const impairment = currentImpairment();
  setText(presenterRefs.impairment, impairment.replaceAll("_", " "));
  setTone(presenterRefs.impairment, impairmentTone(impairment));

  if (presenterRefs.applyRecommended) {
    if (scene.recommendedImpairment) {
      presenterRefs.applyRecommended.hidden = false;
      presenterRefs.applyRecommended.disabled = false;
      presenterRefs.applyRecommended.textContent = `Apply ${scene.recommendedImpairment.replaceAll("_", " ")}`;
    } else {
      presenterRefs.applyRecommended.hidden = true;
      presenterRefs.applyRecommended.disabled = true;
    }
  }
}

function renderPresenterTelemetry() {
  if (!presenterRefs.audienceTelemetry) return;
  const hls = protocolRefs.hls;
  const moq = protocolRefs.moq;
  const drift = driftSeconds();
  const activeTelemetry =
    hls.startupMs !== null ||
    moq.startupMs !== null ||
    hls.liveLatency !== null ||
    moq.liveLatency !== null;

  setText(
    presenterRefs.audienceStatus,
    activeTelemetry ? "reporting live" : "warming up…",
  );
  setTone(presenterRefs.audienceStatus, activeTelemetry ? "good" : "muted");

  presenterRefs.audienceTelemetry.innerHTML = `
    ${detailRow(
      "Time to First Frame",
      `${pairValue("HLS", formatMilliseconds(hls.startupMs), metricTone("startup", hls.startupMs))} | ${pairValue("MoQ", formatMilliseconds(moq.startupMs), metricTone("startup", moq.startupMs))}`,
    )}
    ${detailRow(
      "Drift",
      typeof drift === "number"
        ? toneSpan(
            drift >= 0
              ? `HLS trails MoQ by ${formatSeconds(drift)}`
              : `MoQ trails HLS by ${formatSeconds(Math.abs(drift))}`,
            metricTone("drift", Math.abs(drift)),
          )
        : toneSpan("measuring…", "muted"),
    )}
    ${detailRow(
      "Average Bit-rate",
      `${pairValue("HLS", formatBitrate(hls.bitrate), "good")} | ${pairValue("MoQ", formatBitrate(moq.bitrate), "good")}`,
    )}
    ${detailRow(
      "Stall Count",
      `${pairValue("HLS", `${hls.stallCount ?? 0}`, metricTone("stallCount", hls.stallCount ?? 0))} | ${pairValue("MoQ", `${moq.stallCount ?? 0}`, metricTone("stallCount", moq.stallCount ?? 0))}`,
    )}
    ${detailRow(
      "Latency to Play Head",
      `${pairValue("HLS", formatSeconds(hls.liveLatency), metricTone("liveLatency", hls.liveLatency))} | ${pairValue("MoQ", formatSeconds(moq.liveLatency), metricTone("liveLatency", moq.liveLatency))}`,
    )}
  `;

  renderHealthPanel();
}

function renderHealthPanel() {
  if (!presenterRefs.healthPanel) return;
  const status = stateRef.telemetry?.status || {};
  presenterRefs.healthPanel.innerHTML = `
    ${detailRow("Active scene", toneSpan(currentScene().title, "good"))}
    ${detailRow(
      "HLS player",
      toneSpan(
        protocolRefs.hls.resolution
          ? `${protocolRefs.hls.playbackState} · ${protocolRefs.hls.resolution}`
          : protocolRefs.hls.playbackState,
        detailTone(protocolRefs.hls.playbackState),
      ),
    )}
    ${detailRow(
      "MoQ player",
      toneSpan(
        protocolRefs.moq.resolution
          ? `${protocolRefs.moq.playbackState} · ${protocolRefs.moq.resolution}`
          : protocolRefs.moq.playbackState,
        detailTone(protocolRefs.moq.playbackState),
      ),
    )}
    ${detailRow(
      "Current impairment",
      toneSpan(currentImpairment().replaceAll("_", " "), impairmentTone(currentImpairment())),
    )}
    ${detailRow(
      "Metrics collector",
      status.last_report_ts
        ? toneSpan(`reporting since ${new Date(status.last_report_ts * 1000).toLocaleTimeString()}`, "good")
        : toneSpan("awaiting first report", "muted"),
    )}
  `;
}

function renderPresenterRail() {
  renderSceneList();
  renderSceneDetails();
  renderContext();
  syncImpairmentButtons();
  renderPresenterTelemetry();
}

function renderState(state) {
  if (!state) return;
  stateRef.state = state;
  const scene = currentScene();
  setText(storyRefs.headline, state.headline || scene.headline);
  setText(storyRefs.subhead, state.subhead || scene.subhead);
  setText(storyRefs.impairment, currentImpairment().replaceAll("_", " "));
  setTone(storyRefs.impairment, impairmentTone(currentImpairment()));
  applyStageState();
  renderSharedTelemetry();
  renderPresenterRail();
}

function protocolTelemetryPayload(protocol) {
  const ref = protocolRefs[protocol];
  return {
    startup_ms: ref.startupMs,
    live_latency_seconds: ref.liveLatency,
    bitrate_bps: ref.bitrate,
    stall_count: ref.stallCount,
    playback_state: ref.playbackState,
    resolution: ref.resolution,
  };
}

function pushAudienceTelemetry() {
  const telemetry = {
    protocols: {
      hls: protocolTelemetryPayload("hls"),
      moq: protocolTelemetryPayload("moq"),
    },
    comparison: {
      drift_seconds: driftSeconds(),
      experience_gap_label: storyRefs.sharedDriftMeta.textContent,
    },
    status: {
      audience_connected: true,
    },
  };
  pushPresentationTelemetry(telemetry).catch(() => {});
}

function reportMetrics(protocol) {
  const ref = protocolRefs[protocol];
  if (ref.startupMs === null) return;
  fetch("/metrics/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      protocol,
      latency_seconds: ref.liveLatency,
      startup_ms: ref.startupMs,
      stalls_total: ref.stallCount,
      bitrate_bps: ref.bitrate,
      impairment_profile: currentImpairment(),
    }),
  }).catch(() => {});
}

function renderProtocolTelemetry(protocol) {
  const ref = protocolRefs[protocol];
  updateMetricTile(protocol, "liveLatency", ref.liveLatency, (value) => formatSeconds(value));
  updateMetricTile(protocol, "stallCount", ref.stallCount, (value) => `${value ?? 0}`);
  updateMetricTile(protocol, "bitrate", ref.bitrate, (value) => formatBitrate(value));

  if (ref.detailEl) {
    if (ref.resolution && ref.bitrate) {
      ref.detailEl.textContent = `Rolling average during live playback · ${ref.resolution}`;
    } else if (ref.resolution) {
      ref.detailEl.textContent = `Current render size · ${ref.resolution}`;
    } else {
      ref.detailEl.textContent = "Rolling average during live playback";
    }
  }

  renderPresenterTelemetry();
}

function startHlsPlayer() {
  const ref = protocolRefs.hls;
  const video = ref.videoSurface;
  const startTs = performance.now();
  let startupRecorded = false;
  let stallOpen = false;
  let hls;
  let bandwidthEstimate = 0;

  if (!window.Hls || !window.Hls.isSupported()) {
    ref.status.textContent = "HLS not supported in this browser";
    ref.playbackState = "unsupported";
    renderHealthPanel();
    return;
  }

  hls = new window.Hls({
    liveSyncDurationCount: 3,
    liveMaxLatencyDurationCount: 60,
    maxLiveSyncPlaybackRate: 1.0,
    maxBufferLength: 10,
    enableWorker: true,
    lowLatencyMode: false,
    abrEwmaFastLive: 2,
    abrEwmaSlowLive: 4,
  });

  hls.loadSource("/hls/master.m3u8");
  hls.attachMedia(video);

  hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
    ref.status.textContent = "Buffering…";
    video.play().catch(() => {});
  });

  video.addEventListener("playing", () => {
    ref.overlay.classList.add("hidden");
    ref.status.textContent = "Playing live";
    ref.playbackState = "playing";
    if (stallOpen) stallOpen = false;
    if (!startupRecorded && startTs !== null) {
      ref.startupMs = performance.now() - startTs;
      startupRecorded = true;
      renderSharedTelemetry();
    }
    renderHealthPanel();
  });

  video.addEventListener("waiting", () => {
    ref.overlay.classList.remove("hidden");
    ref.status.textContent = startupRecorded ? "Rebuffering…" : "Buffering…";
    ref.playbackState = "buffering";
    if (startupRecorded && !stallOpen) {
      ref.stallCount += 1;
      stallOpen = true;
    }
    renderProtocolTelemetry("hls");
    renderSharedTelemetry();
  });

  hls.on(window.Hls.Events.FRAG_LOADED, (_, data) => {
    const bytes = data.frag.stats.total;
    const duration = data.frag.duration;
    if (duration > 0 && bytes > 0) {
      recordBitrateSample("hls", (bytes * 8) / duration);
      renderProtocolTelemetry("hls");
    }

    const stats = data.frag.stats;
    const transferMs = stats.loading?.end - stats.loading?.first;
    if (transferMs > 1 && stats.total > 0) {
      const measuredBps = (stats.total * 8 * 1000) / transferMs;
      const alpha = 0.6;
      bandwidthEstimate =
        bandwidthEstimate > 0
          ? alpha * measuredBps + (1 - alpha) * bandwidthEstimate
          : measuredBps;
      window._presentationHlsBandwidthBps = bandwidthEstimate;
    }
  });

  hls.on(window.Hls.Events.LEVEL_SWITCHED, (_, data) => {
    stateRef.hlsLevel = data.level;
    stateRef.hlsLevelCount = hls.levels?.length || 0;
  });

  setInterval(() => {
    if (video.paused || video.readyState < 2) return;
    if (typeof hls.latency === "number" && hls.latency > 0) {
      ref.liveLatency = hls.latency;
    }
    ref.resolution =
      video.videoWidth && video.videoHeight
        ? `${video.videoWidth}×${video.videoHeight}`
        : null;
    renderProtocolTelemetry("hls");
    renderSharedTelemetry();
  }, 1000);
}

function startMoqPlayer() {
  const ref = protocolRefs.moq;
  let watch = ref.videoSurface;
  const MOQ_URL = `http://${window.location.hostname}:4443`;
  const MOQ_HI = "stream_hi";
  const MOQ_LO = "stream_lo";
  const MOQ_STARTUP_POLL_MS = 50;
  const MOQ_ABR_POLL_MS = 500;
  const MOQ_ABR_COOLDOWN_MS = 5000;
  const RENDITION_BPS = {
    [MOQ_HI]: 4_000_000,
    [MOQ_LO]: 500_000,
  };
  const ABR_DOWN_BPS = 3_600_000;
  const ABR_UP_BPS = 5_200_000;
  let currentName = MOQ_HI;
  let startupDone = false;
  let startTs = performance.now();
  let prevBroadcast = null;
  let stallOpen = false;
  let abrCooldownUntil = 0;

  watch.url = new URL(MOQ_URL);
  watch.name = currentName;
  ref.streamName = currentName;

  function replaceWatchEl() {
    const parent = watch.parentNode;
    if (!parent) return;
    const next = document.createElement("hang-watch");
    next.id = watch.id;
    next.setAttribute("muted", "");
    next.setAttribute("latency", watch.getAttribute("latency") || "2000");
    next.innerHTML = "<canvas></canvas>";
    parent.replaceChild(next, watch);
    watch = next;
    ref.videoSurface = next;
  }

  function reconnect(targetName = currentName) {
    currentName = targetName;
    ref.streamName = currentName;
    ref.playbackState = "connecting";
    ref.status.textContent = "Reconnecting…";
    ref.overlay.classList.remove("hidden");
    watch.url = new URL(MOQ_URL);
    watch.name = currentName;
    renderProtocolTelemetry("moq");
    renderHealthPanel();
  }

  function switchRendition(targetName) {
    if (targetName === currentName) return;
    currentName = targetName;
    ref.streamName = currentName;
    prevBroadcast = null;
    abrCooldownUntil = performance.now() + MOQ_ABR_COOLDOWN_MS;
    ref.playbackState = "connecting";
    ref.status.textContent = "Switching rendition…";
    ref.overlay.classList.remove("hidden");
    replaceWatchEl();
    watch.url = new URL(MOQ_URL);
    watch.name = currentName;
    renderProtocolTelemetry("moq");
    renderHealthPanel();
  }

  const startupProbe = setInterval(() => {
    if (startupDone) {
      clearInterval(startupProbe);
      return;
    }

    const instance = watch.active ? watch.active.peek() : undefined;
    const broadcast = instance?.broadcast.status ? instance.broadcast.status.peek() : undefined;
    const canvas = watch.querySelector("canvas");
    const hasRenderedFrame =
      broadcast === "live" && canvas && canvas.width > 1 && canvas.height > 1;

    if (!hasRenderedFrame) return;

    startupDone = true;
    ref.startupMs = performance.now() - startTs;
    renderProtocolTelemetry("moq");
    renderSharedTelemetry();
  }, MOQ_STARTUP_POLL_MS);

  setInterval(() => {
    if (!startupDone) return;
    if (performance.now() < abrCooldownUntil) return;
    const estimated = window._presentationHlsBandwidthBps || 0;
    const hlsOnLowestRendition =
      stateRef.hlsLevelCount > 1 && stateRef.hlsLevel === stateRef.hlsLevelCount - 1;
    const hlsSuggestsConstrainedPath = hlsOnLowestRendition && estimated < ABR_UP_BPS;

    if (currentName === MOQ_HI && (hlsSuggestsConstrainedPath || (estimated > 0 && estimated < ABR_DOWN_BPS))) {
      switchRendition(MOQ_LO);
    } else if (currentName === MOQ_LO && estimated > ABR_UP_BPS) {
      switchRendition(MOQ_HI);
    }
  }, MOQ_ABR_POLL_MS);

  setInterval(() => {
    const instance = watch.active ? watch.active.peek() : undefined;
    if (!instance) {
      ref.overlay.classList.remove("hidden");
      ref.status.textContent = "Waiting for relay…";
      ref.playbackState = "connecting";
      prevBroadcast = null;
      renderHealthPanel();
      return;
    }

    const broadcast = instance.broadcast.status
      ? instance.broadcast.status.peek()
      : undefined;

    if (broadcast === "live") {
      ref.overlay.classList.add("hidden");
      ref.playbackState = "playing";
      ref.status.textContent = "Playing live";
      ref.liveLatency = currentName === MOQ_HI ? 2 : 2.3;
      recordBitrateSample("moq", RENDITION_BPS[currentName] || RENDITION_BPS[MOQ_LO]);
    } else if (broadcast === "loading") {
      ref.overlay.classList.remove("hidden");
      ref.status.textContent = "Buffering…";
      ref.playbackState = "buffering";
    } else {
      ref.overlay.classList.remove("hidden");
      ref.status.textContent = "Waiting for broadcast…";
      ref.playbackState = "connecting";
    }

    if (broadcast !== prevBroadcast) {
      if (broadcast === "live") {
        if (stallOpen) stallOpen = false;
      } else if (broadcast === "loading") {
        if (startupDone && !stallOpen) {
          ref.stallCount += 1;
          stallOpen = true;
        }
      }
      prevBroadcast = broadcast;
    }

    const canvas = watch.querySelector("canvas");
    if (canvas && canvas.width > 1) {
      ref.resolution = `${canvas.width}×${canvas.height}`;
    }
    renderProtocolTelemetry("moq");
    renderSharedTelemetry();
  }, 500);
}

function startDriftMeasurement() {
  const REGION_X = 20;
  const REGION_Y = 20;
  const REGION_W = 320;
  const REGION_H = 60;
  const CHANGE_THRESH = 2000;
  const HISTORY_MS = 14000;
  const MIN_MATCHES = 2;
  const oc =
    typeof OffscreenCanvas === "function"
      ? new OffscreenCanvas(REGION_W, REGION_H)
      : Object.assign(document.createElement("canvas"), {
          width: REGION_W,
          height: REGION_H,
        });
  const ctx = oc.getContext("2d", { willReadFrequently: true });
  let hlsFp = null;
  let moqFp = null;
  let hlsTrans = [];
  let moqTrans = [];
  let moqReadable = true;

  function fingerprint(src) {
    try {
      ctx.drawImage(src, REGION_X, REGION_Y, REGION_W, REGION_H, 0, 0, REGION_W, REGION_H);
      const data = ctx.getImageData(0, 0, REGION_W, REGION_H).data;
      let sum = 0;
      for (let i = 0; i < data.length; i += 16) sum += data[i];
      return sum;
    } catch {
      return null;
    }
  }

  function prune(arr, now) {
    const cutoff = now - HISTORY_MS;
    while (arr.length && arr[0].ts < cutoff) arr.shift();
  }

  function updateDrift(now) {
    prune(hlsTrans, now);
    prune(moqTrans, now);
    if (hlsTrans.length < 2 || moqTrans.length < 2) return;
    const bins = {};
    for (const h of hlsTrans) {
      for (const m of moqTrans) {
        const dt = h.ts - m.ts;
        if (dt > 0 && dt < HISTORY_MS) {
          const bin = Math.floor(dt / 1000);
          bins[bin] = (bins[bin] || 0) + 1;
        }
      }
    }

    let modeBin = -1;
    let modeCount = 0;
    Object.entries(bins).forEach(([bin, count]) => {
      if (count > modeCount) {
        modeCount = count;
        modeBin = Number(bin);
      }
    });
    if (modeBin < 0 || modeCount < MIN_MATCHES) return;

    const center = (modeBin + 0.5) * 1000;
    const refined = [];
    for (const h of hlsTrans) {
      for (const m of moqTrans) {
        const dt = h.ts - m.ts;
        if (Math.abs(dt - center) < 500) refined.push(dt);
      }
    }
    if (!refined.length) return;
    stateRef.driftSeconds = refined.reduce((sum, value) => sum + value, 0) / refined.length / 1000;
    renderSharedTelemetry();
  }

  setInterval(() => {
    const now = performance.now();
    const video = protocolRefs.hls.videoSurface;
    const moqCanvas = protocolRefs.moq.videoSurface.querySelector("canvas");
    if (video && video.readyState >= 2 && !video.paused) {
      const fp = fingerprint(video);
      if (fp !== null) {
        if (hlsFp !== null && Math.abs(fp - hlsFp) > CHANGE_THRESH) {
          hlsTrans.push({ ts: now });
          updateDrift(now);
        }
        hlsFp = fp;
      }
    }
    if (moqReadable && moqCanvas && moqCanvas.width > 1) {
      const fp = fingerprint(moqCanvas);
      if (fp === null || fp < 10) {
        moqReadable = false;
        return;
      }
      if (moqFp !== null && Math.abs(fp - moqFp) > CHANGE_THRESH) {
        moqTrans.push({ ts: now });
      }
      moqFp = fp;
    }
  }, 250);
}

function syncSnapshot(snapshot) {
  if (snapshot?.telemetry) {
    stateRef.telemetry = snapshot.telemetry;
  }
  if (snapshot?.state) {
    renderState(snapshot.state);
    return;
  }
  renderPresenterRail();
}

async function applyScene(sceneId) {
  const nextState = buildSceneState(sceneId, { activeImpairment: currentImpairment() });
  syncSnapshot(await setPresentationState(nextState));
}

async function applyRecommendedImpairment() {
  const scene = currentScene();
  if (!scene.recommendedImpairment) return;
  await applyImpairmentAndSync(scene.recommendedImpairment);
}

async function applyImpairmentAndSync(profile) {
  await applyImpairment(profile);
  syncSnapshot(await setPresentationState({ activeImpairment: profile }));
}

function isTextInputTarget(target) {
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    (target instanceof HTMLElement && target.isContentEditable)
  );
}

function bindPresenterControls() {
  presenterRefs.prevScene?.addEventListener("click", () => {
    applyScene(getAdjacentScene(currentScene().id, -1).id).catch((error) => console.error(error));
  });
  presenterRefs.nextScene?.addEventListener("click", () => {
    applyScene(getAdjacentScene(currentScene().id, 1).id).catch((error) => console.error(error));
  });
  presenterRefs.resetBaseline?.addEventListener("click", () => {
    applyImpairmentAndSync("baseline").catch((error) => console.error(error));
  });
  presenterRefs.applyRecommended?.addEventListener("click", () => {
    applyRecommendedImpairment().catch((error) => console.error(error));
  });

  impairmentButtons.forEach((button) => {
    button.addEventListener("click", () => {
      applyImpairmentAndSync(button.dataset.impairment).catch((error) => console.error(error));
    });
  });

  presenterRefs.sceneControls?.addEventListener("toggle", () => {
    if (presenterRefs.sceneControlsIndicator) {
      presenterRefs.sceneControlsIndicator.textContent = presenterRefs.sceneControls.open ? "Hide" : "Show";
    }
  });

  window.addEventListener("keydown", (event) => {
    if (isTextInputTarget(event.target) || event.repeat) return;

    if (event.key === "ArrowRight") {
      event.preventDefault();
      applyScene(getAdjacentScene(currentScene().id, 1).id).catch((error) => console.error(error));
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      applyScene(getAdjacentScene(currentScene().id, -1).id).catch((error) => console.error(error));
    }
    if (event.key.toLowerCase() === "b") {
      event.preventDefault();
      applyImpairmentAndSync("baseline").catch((error) => console.error(error));
    }
    if (event.key.toLowerCase() === "j") {
      event.preventDefault();
      applyImpairmentAndSync("jitter").catch((error) => console.error(error));
    }
    if (event.key.toLowerCase() === "s") {
      event.preventDefault();
      applyImpairmentAndSync("squeeze").catch((error) => console.error(error));
    }
    if (event.key.toLowerCase() === "o") {
      event.preventDefault();
      applyImpairmentAndSync("outage").catch((error) => console.error(error));
    }
    if (event.key.toLowerCase() === "m") {
      event.preventDefault();
      applyImpairmentAndSync("stale_manifest").catch((error) => console.error(error));
    }
  });
}

async function bootstrap() {
  syncSnapshot(await getPresentationSnapshot());

  requestAnimationFrame(updateStagePaths);
  if (typeof ResizeObserver === "function" && stageMap) {
    new ResizeObserver(() => requestAnimationFrame(updateStagePaths)).observe(stageMap);
  }

  try {
    const impairment = await getImpairmentStatus();
    if (impairment?.profile && impairment.profile !== currentImpairment()) {
      syncSnapshot(await setPresentationState({ activeImpairment: impairment.profile }));
    }
  } catch {
    // best effort only
  }

  connectPresentationEvents((payload) => {
    syncSnapshot(payload);
  });

  initializePresenterShell();
  bindPresenterControls();

  await customElements.whenDefined("hang-watch");
  startHlsPlayer();
  startMoqPlayer();
  startDriftMeasurement();

  setInterval(() => {
    renderProtocolTelemetry("hls");
    renderProtocolTelemetry("moq");
    renderSharedTelemetry();
    pushAudienceTelemetry();
  }, 2000);

  setInterval(() => {
    reportMetrics("hls");
    reportMetrics("moq");
  }, 5000);
}

bootstrap().catch((error) => {
  console.error(error);
  setText(storyRefs.subhead, `Presentation workspace failed to start: ${error.message}`);
  setText(presenterRefs.subhead, `Presentation workspace failed to start: ${error.message}`);
});

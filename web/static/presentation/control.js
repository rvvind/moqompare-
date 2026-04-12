import {
  applyImpairment,
  connectPresentationEvents,
  formatBitrate,
  formatMilliseconds,
  formatSeconds,
  getPresentationSnapshot,
  getImpairmentStatus,
  impairmentTone,
  setPresentationState,
} from "./api.js";
import {
  PRESENTATION_SCENES,
  buildSceneState,
  getAdjacentScene,
  getScene,
  getSceneIndex,
} from "./scenes.js";

const refs = {
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
};

const state = {
  sceneId: "opening",
  snapshot: null,
};

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
    hls: "A 500 kbps cap starves TCP. hls.js sees the reduced throughput and switches to the low rendition at 640×360 and 500 kbps.",
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

function setTone(el, tone) {
  if (!el) return;
  el.classList.remove("tone-good", "tone-warn", "tone-bad", "tone-muted");
  el.classList.add(`tone-${tone}`);
}

function renderSceneList() {
  refs.sceneItems.innerHTML = "";
  PRESENTATION_SCENES.forEach((scene) => {
    const button = document.createElement("button");
    button.className = `scene-item${scene.id === state.sceneId ? " active" : ""}`;
    button.innerHTML = `
      <div class="title">${scene.title}</div>
      <div class="copy">${scene.subhead}</div>
    `;
    button.addEventListener("click", () => applyScene(scene.id));
    refs.sceneItems.appendChild(button);
  });
}

function renderSceneDetails() {
  const scene = getScene(state.sceneId);
  const index = getSceneIndex(scene.id);
  refs.scenePosition.textContent = `${index + 1} / ${PRESENTATION_SCENES.length}`;
  refs.sceneCurrentTitle.textContent = scene.title;
  refs.headline.textContent = state.snapshot?.state?.headline || scene.headline;
  refs.subhead.textContent = state.snapshot?.state?.subhead || scene.subhead;
  const impairment = state.snapshot?.state?.activeImpairment || "baseline";
  refs.impairment.textContent = impairment.replaceAll("_", " ");
  setTone(refs.impairment, impairmentTone(impairment));
}

function renderContext() {
  const activeImpairment = state.snapshot?.state?.activeImpairment || "baseline";
  refs.contextPanel.innerHTML = IMPAIRMENT_CONTEXT.map((item) => `
    <article class="context-item${item.id === activeImpairment ? " active" : ""}">
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
  `).join("");
}

function detailRow(key, value, tone = "muted") {
  return `
    <div class="detail-row">
      <span class="key">${key}</span>
      <span class="val tone-${tone}">${value}</span>
    </div>
  `;
}

function renderTelemetry() {
  const telemetry = state.snapshot?.telemetry;
  const status = telemetry?.status || {};
  const protocols = telemetry?.protocols || {};
  refs.audienceStatus.textContent = status.audience_connected
    ? "audience connected"
    : "waiting for audience…";
  setTone(refs.audienceStatus, status.audience_connected ? "good" : "muted");

  refs.audienceTelemetry.innerHTML = `
    <div class="detail-row">
      <span class="key">Start Time</span>
      <span class="val">${protocols.hls?.startup_ms ? `HLS ${formatMilliseconds(protocols.hls.startup_ms)}` : "HLS —"} | ${protocols.moq?.startup_ms ? `MoQ ${formatMilliseconds(protocols.moq.startup_ms)}` : "MoQ —"}</span>
    </div>
    <div class="detail-row">
      <span class="key">Experience Gap</span>
      <span class="val">${telemetry?.comparison?.experience_gap_label || "measuring…"}</span>
    </div>
    <div class="detail-row">
      <span class="key">HLS Behind Live</span>
      <span class="val">${formatSeconds(protocols.hls?.live_latency_seconds)}</span>
    </div>
    <div class="detail-row">
      <span class="key">MoQ Behind Live</span>
      <span class="val">${formatSeconds(protocols.moq?.live_latency_seconds)}</span>
    </div>
    <div class="detail-row">
      <span class="key">HLS Delivered Quality</span>
      <span class="val">${formatBitrate(protocols.hls?.bitrate_bps)}</span>
    </div>
    <div class="detail-row">
      <span class="key">MoQ Delivered Quality</span>
      <span class="val">${formatBitrate(protocols.moq?.bitrate_bps)}</span>
    </div>
    <div class="detail-row">
      <span class="key">Playback Freezes</span>
      <span class="val">HLS ${protocols.hls?.stall_count ?? 0} | MoQ ${protocols.moq?.stall_count ?? 0}</span>
    </div>
  `;

  refs.healthPanel.innerHTML = `
    ${detailRow("Audience page", status.audience_connected ? '<span class="status-dot good"></span>connected' : '<span class="status-dot muted"></span>not reporting', status.audience_connected ? "good" : "muted")}
    ${detailRow("HLS telemetry", protocols.hls?.playback_state || "waiting", protocols.hls?.playback_state === "playing" ? "good" : protocols.hls?.playback_state ? "warn" : "muted")}
    ${detailRow("MoQ telemetry", protocols.moq?.playback_state || "waiting", protocols.moq?.playback_state === "playing" ? "good" : protocols.moq?.playback_state ? "warn" : "muted")}
    ${detailRow("Last audience report", status.last_report_ts ? new Date(status.last_report_ts * 1000).toLocaleTimeString() : "never", status.last_report_ts ? "good" : "muted")}
  `;
}

async function applyScene(sceneId) {
  state.sceneId = sceneId;
  const impairment = state.snapshot?.state?.activeImpairment || "baseline";
  const nextState = buildSceneState(sceneId, { activeImpairment: impairment });
  state.snapshot = await setPresentationState(nextState);
  renderSceneList();
  renderSceneDetails();
  renderContext();
}

async function applyRecommendedImpairment() {
  const scene = getScene(state.sceneId);
  if (!scene.recommendedImpairment) return;
  await applyImpairmentAndSync(scene.recommendedImpairment);
}

async function applyImpairmentAndSync(profile) {
  await applyImpairment(profile);
  state.snapshot = await setPresentationState({ activeImpairment: profile });
  renderSceneDetails();
  renderContext();
}

async function syncFromServer(snapshot) {
  state.snapshot = snapshot;
  state.sceneId = snapshot.state?.sceneId || state.sceneId;
  renderSceneList();
  renderSceneDetails();
  renderContext();
  renderTelemetry();
}

async function bootstrap() {
  state.snapshot = await getPresentationSnapshot();
  state.sceneId = state.snapshot.state?.sceneId || "opening";

  try {
    const impairment = await getImpairmentStatus();
    if (impairment?.profile && impairment.profile !== state.snapshot.state?.activeImpairment) {
      state.snapshot = await setPresentationState({ activeImpairment: impairment.profile });
    }
  } catch {
    // best effort only
  }

  renderSceneList();
  renderSceneDetails();
  renderContext();
  renderTelemetry();

  connectPresentationEvents((snapshot) => {
    syncFromServer(snapshot).catch((error) => console.error(error));
  });

  document.getElementById("prev-scene").addEventListener("click", () => {
    applyScene(getAdjacentScene(state.sceneId, -1).id).catch((error) => console.error(error));
  });
  document.getElementById("next-scene").addEventListener("click", () => {
    applyScene(getAdjacentScene(state.sceneId, 1).id).catch((error) => console.error(error));
  });
  document.getElementById("reset-baseline").addEventListener("click", () => {
    applyImpairmentAndSync("baseline").catch((error) => console.error(error));
  });
  document.getElementById("apply-recommended").addEventListener("click", () => {
    applyRecommendedImpairment().catch((error) => console.error(error));
  });

  document.querySelectorAll("[data-impairment]").forEach((button) => {
    button.addEventListener("click", () => {
      applyImpairmentAndSync(button.dataset.impairment).catch((error) => console.error(error));
    });
  });

  refs.sceneControls.addEventListener("toggle", () => {
    refs.sceneControlsIndicator.textContent = refs.sceneControls.open ? "Hide" : "Show";
  });

  window.addEventListener("keydown", (event) => {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
    if (event.key === "ArrowRight") applyScene(getAdjacentScene(state.sceneId, 1).id).catch(console.error);
    if (event.key === "ArrowLeft") applyScene(getAdjacentScene(state.sceneId, -1).id).catch(console.error);
    if (event.key.toLowerCase() === "b") applyImpairmentAndSync("baseline").catch(console.error);
    if (event.key.toLowerCase() === "j") applyImpairmentAndSync("jitter").catch(console.error);
    if (event.key.toLowerCase() === "s") applyImpairmentAndSync("squeeze").catch(console.error);
    if (event.key.toLowerCase() === "o") applyImpairmentAndSync("outage").catch(console.error);
    if (event.key.toLowerCase() === "m") applyImpairmentAndSync("stale_manifest").catch(console.error);
  });
}

bootstrap().catch((error) => {
  console.error(error);
  refs.subhead.textContent = `Presenter console failed to start: ${error.message}`;
});

const MOQ_URL = `http://${window.location.hostname}:4443`;

export async function ensureWatchReady() {
  await customElements.whenDefined("hang-watch");
}

function buildWatchElement(id, latencyMs = 2000) {
  const watch = document.createElement("hang-watch");
  if (id) watch.id = id;
  watch.setAttribute("muted", "");
  watch.setAttribute("reload", "");
  watch.setAttribute("latency", String(latencyMs || 2000));
  watch.innerHTML = "<canvas></canvas>";
  return watch;
}

export function retuneWatch(slotEl, currentWatch, streamName, latencyMs = 2000) {
  const next = buildWatchElement(currentWatch?.id || "", latencyMs);
  if (currentWatch && currentWatch.parentNode === slotEl) {
    slotEl.replaceChild(next, currentWatch);
  } else {
    slotEl.innerHTML = "";
    slotEl.appendChild(next);
  }
  next.url = new URL(MOQ_URL);
  next.name = streamName;
  return next;
}

export function readWatchState(watch) {
  if (!watch) {
    return {
      state: "idle",
      hasFrame: false,
      resolution: null,
    };
  }

  const instance = watch.active ? watch.active.peek() : undefined;
  if (!instance) {
    return {
      state: "connecting",
      hasFrame: false,
      resolution: null,
    };
  }

  const broadcast = instance.broadcast?.status
    ? instance.broadcast.status.peek()
    : undefined;
  const canvas = watch.querySelector("canvas");
  const hasFrame = Boolean(canvas && canvas.width > 1 && canvas.height > 1);
  const resolution = hasFrame ? `${canvas.width}×${canvas.height}` : null;

  if (broadcast === "live") {
    return {
      state: "live",
      hasFrame,
      resolution,
    };
  }

  if (broadcast === "loading") {
    return {
      state: "buffering",
      hasFrame,
      resolution,
    };
  }

  return {
    state: "connecting",
    hasFrame,
    resolution,
  };
}

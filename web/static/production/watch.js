const MOQ_URL = `http://${window.location.hostname}:4443`;

export async function ensureWatchReady() {
  await customElements.whenDefined("moq-watch");
}

function buildWatchElement(id, latency = "real-time") {
  const watch = document.createElement("moq-watch");
  if (id) watch.id = id;
  watch.setAttribute("muted", "");
  watch.setAttribute("reload", "");
  watch.setAttribute("latency", String(latency || "real-time"));
  watch.innerHTML = "<canvas></canvas>";
  return watch;
}

export function retuneWatch(slotEl, currentWatch, streamName, latency = "real-time") {
  const next = buildWatchElement(currentWatch?.id || "", latency);
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

  const activeBroadcast = watch.broadcast?.active
    ? watch.broadcast.active.peek()
    : undefined;
  if (!activeBroadcast) {
    return {
      state: "connecting",
      hasFrame: false,
      resolution: null,
    };
  }

  const broadcast = watch.broadcast?.status
    ? watch.broadcast.status.peek()
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

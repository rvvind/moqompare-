export const PRESENTATION_SCENES = [
  {
    id: "opening",
    title: "One Live Source",
    headline: "One live source, two delivery paths.",
    subhead:
      "The same live video enters both systems so the audience can focus on delivery behavior, not content differences.",
    notes:
      "Open with the shared source. Emphasize that both panes are the same live feed and the comparison is architectural, not editorial.",
    focus: "split",
    spotlight: {
      nodes: ["source", "packager", "origin", "manifest-proxy", "publisher", "relay", "viewer-hls", "viewer-moq"],
      edges: ["source-packager", "hls-origin", "hls-manifest", "hls-delivery", "hls-poll", "moq-publish", "moq-relay", "moq-delivery"],
    },
    overlay: {
      title: "Shared source",
      body: "Both experiences begin with the same live video, packaged once and delivered through two protocols.",
      tone: "good",
    },
    promotedMetrics: ["liveLatency", "startup", "drift"],
  },
  {
    id: "hls-path",
    title: "HLS Delivery",
    headline: "HLS advances by polling for what comes next.",
    subhead:
      "The player checks the manifest, discovers new segments, then fetches the next chunk of video over HTTP.",
    notes:
      "Spotlight the control loop. This is the moment to explain manifests and segments in one sentence without going deep on internals.",
    focus: "hls",
    spotlight: {
      nodes: ["source", "packager", "origin", "manifest-proxy", "viewer-hls"],
      edges: ["source-packager", "hls-origin", "hls-manifest", "hls-delivery", "hls-poll"],
    },
    overlay: {
      title: "Manifest + segment loop",
      body: "HLS needs fresh delivery instructions before it can request the next piece of media.",
      tone: "warn",
    },
    promotedMetrics: ["startup", "liveLatency", "drift"],
  },
  {
    id: "moq-path",
    title: "MoQ Delivery",
    headline: "MoQ keeps the newest media moving forward.",
    subhead:
      "Instead of waiting for playlist refreshes, media objects are published into a relay and pushed toward the viewer.",
    notes:
      "Keep this simple. MoQ is the push path. Relay is the audience-friendly concept to anchor on.",
    focus: "moq",
    spotlight: {
      nodes: ["source", "packager", "publisher", "relay", "viewer-moq"],
      edges: ["source-packager", "moq-publish", "moq-relay", "moq-delivery"],
    },
    overlay: {
      title: "Continuous object flow",
      body: "MoQ keeps the freshest media moving through the relay without a manifest polling loop.",
      tone: "good",
    },
    promotedMetrics: ["liveLatency", "bitrate", "drift"],
  },
  {
    id: "baseline-compare",
    title: "Baseline",
    headline: "Both paths are healthy. Now stress delivery, not the source.",
    subhead:
      "The interesting difference appears when the network becomes unstable and each protocol has to recover.",
    notes:
      "Use this as the handoff from architecture explanation to live comparison. Invite the audience to watch what changes when you impair delivery.",
    focus: "split",
    spotlight: {
      nodes: ["origin", "manifest-proxy", "relay", "viewer-hls", "viewer-moq"],
      edges: ["hls-delivery", "hls-poll", "moq-delivery"],
    },
    overlay: {
      title: "Ready for stress",
      body: "The source stays healthy. The next changes you see come from delivery behavior.",
      tone: "good",
    },
    promotedMetrics: ["liveLatency", "stallCount", "drift"],
  },
  {
    id: "squeeze-demo",
    title: "Bandwidth Squeeze",
    headline: "Constrained bandwidth changes what quality can be delivered.",
    subhead:
      "This impairment squeezes delivery capacity so the audience can see how each path adapts under pressure.",
    notes:
      "Draw attention to delivered quality and distance from live. If quality steps down, explain that the source never changed.",
    focus: "split",
    spotlight: {
      nodes: ["viewer-hls", "viewer-moq", "relay", "manifest-proxy"],
      edges: ["hls-delivery", "moq-delivery"],
    },
    overlay: {
      title: "Bandwidth constrained here",
      body: "The delivery path is narrowed. Watch quality and distance from live respond.",
      tone: "warn",
    },
    promotedMetrics: ["bitrate", "liveLatency", "stallCount"],
    recommendedImpairment: "squeeze",
  },
  {
    id: "outage-demo",
    title: "Burst Outage",
    headline: "A short outage tests how quickly each path can recover.",
    subhead:
      "Both viewers lose delivery briefly. The comparison is about how they return to live playback once the path recovers.",
    notes:
      "This is where playback freezes and recovery are easiest to explain. Frame it as viewer experience rather than protocol purity.",
    focus: "split",
    spotlight: {
      nodes: ["viewer-hls", "viewer-moq", "relay", "manifest-proxy"],
      edges: ["hls-delivery", "moq-delivery"],
    },
    overlay: {
      title: "Delivery interrupted",
      body: "The source keeps running. The question is how each path recovers once the outage clears.",
      tone: "bad",
    },
    promotedMetrics: ["stallCount", "liveLatency", "startup"],
    recommendedImpairment: "outage",
  },
  {
    id: "stale-manifest-demo",
    title: "Stale Manifest",
    headline: "This time only the HLS control path is impaired.",
    subhead:
      "The HLS manifest stops advancing while MoQ keeps receiving fresh media objects through the relay.",
    notes:
      "This is the cleanest architectural proof point. Point to the frozen control path and say MoQ is unaffected because it is not waiting on that loop.",
    focus: "stale-manifest",
    spotlight: {
      nodes: ["origin", "manifest-proxy", "viewer-hls", "relay", "viewer-moq"],
      edges: ["hls-manifest", "hls-poll", "hls-delivery", "moq-delivery"],
    },
    overlay: {
      title: "HLS control path frozen",
      body: "HLS keeps asking the same stale question. MoQ keeps receiving fresh media.",
      tone: "bad",
    },
    promotedMetrics: ["liveLatency", "drift", "stallCount"],
    recommendedImpairment: "stale_manifest",
  },
  {
    id: "business-close",
    title: "Executive Summary",
    headline: "The business value is a steadier live experience under imperfect conditions.",
    subhead:
      "MoQ is not just technically different. It keeps viewers closer to live with fewer visible disruptions when delivery conditions degrade.",
    notes:
      "Close on viewer experience and business impact. Don’t summarize protocol mechanics again.",
    focus: "split",
    spotlight: {
      nodes: ["viewer-hls", "viewer-moq", "relay", "manifest-proxy"],
      edges: ["hls-delivery", "moq-delivery"],
    },
    overlay: {
      title: "Why it matters",
      body: "Less delay, fewer visible interruptions, and a more resilient live experience under stress.",
      tone: "good",
    },
    promotedMetrics: ["liveLatency", "stallCount", "bitrate"],
  },
];

export const PRESENTATION_SCENE_MAP = Object.fromEntries(
  PRESENTATION_SCENES.map((scene) => [scene.id, scene]),
);

export function getScene(sceneId) {
  return PRESENTATION_SCENE_MAP[sceneId] || PRESENTATION_SCENES[0];
}

export function getSceneIndex(sceneId) {
  return PRESENTATION_SCENES.findIndex((scene) => scene.id === sceneId);
}

export function getAdjacentScene(sceneId, direction) {
  const index = getSceneIndex(sceneId);
  if (index < 0) return PRESENTATION_SCENES[0];
  const nextIndex = Math.min(
    PRESENTATION_SCENES.length - 1,
    Math.max(0, index + direction),
  );
  return PRESENTATION_SCENES[nextIndex];
}

export function buildSceneState(sceneId, extra = {}) {
  const scene = getScene(sceneId);
  return {
    sceneId: scene.id,
    headline: scene.headline,
    subhead: scene.subhead,
    focus: scene.focus,
    overlay: scene.overlay,
    spotlight: scene.spotlight,
    promotedMetrics: scene.promotedMetrics,
    ...extra,
  };
}

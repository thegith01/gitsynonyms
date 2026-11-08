// Capture Immersive Translate's live subtitle behavior for a time window.
//
// Usage:
//   node scripts/benchmarks/capture_immersive_translate.mjs 300 90 capture_300.json
//
// Requires Chrome started with --remote-debugging-port=9222 (or CDP_PORT), a
// youtube.com/watch page, and the Immersive Translate extension enabled. The
// output is temporary evidence; commit conclusions to observed-YYYY-MM-DD.json,
// not the capture file.
//
// Two observations end up in the JSON:
//   events  - one entry per visible source/target change, sampled from the
//             extension's shadow-DOM caption window plus the native YouTube
//             caption segments.
//   network - the requests and (for translation calls) the decoded response
//             body issued by the extension's service worker / offscreen
//             document. Captions and translation run off-page, so enabling
//             Network on the page target alone sees nothing.
import fs from "node:fs";

const PORT = process.env.CDP_PORT || "9222";
const BASE = `http://127.0.0.1:${PORT}`;
const EXT_ID = process.env.IMT_EXT_ID || "bpoadfkcbjbfhfodiogcnhhhpibjhbnh";
const startAt = Number(process.argv[2] || 300);
const duration = Number(process.argv[3] || 90);
const outFile = process.argv[4] || "capture.json";

function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  const pending = new Map();
  const listeners = [];
  let id = 0;
  const ready = new Promise((res, rej) => {
    ws.addEventListener("open", res, { once: true });
    ws.addEventListener("error", rej, { once: true });
  });
  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error)));
      else resolve(msg.result);
      return;
    }
    for (const listener of listeners) listener(msg);
  });
  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      const myId = ++id;
      pending.set(myId, { resolve, reject });
      const payload = { id: myId, method, params };
      if (sessionId) payload.sessionId = sessionId;
      ws.send(JSON.stringify(payload));
    });
  return { ws, ready, send, on: (fn) => listeners.push(fn) };
}

const targets = await (await fetch(`${BASE}/json/list`)).json();
const page = targets.find((t) => t.type === "page" && t.url.includes("youtube.com/watch"));
if (!page) throw new Error("no youtube page");
const version = await (await fetch(`${BASE}/json/version`)).json();

// ---------------------------------------------------------------------------
// Page connection: drive the video and sample the visible caption window.
// ---------------------------------------------------------------------------
const pageCdp = connect(page.webSocketDebuggerUrl);
await pageCdp.ready;
const send = pageCdp.send;

const evalPage = async (expression) => {
  const res = await send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (res.exceptionDetails) throw new Error(res.exceptionDetails.text || "eval failed");
  return res.result.value;
};

// ---------------------------------------------------------------------------
// Browser connection: attach to the extension's own execution contexts.
// ---------------------------------------------------------------------------
const network = [];
const networkById = new Map();
const capturedSessions = new Map();
const networkPattern =
  /(timedtext|translate|cognitive|bing|googleapis|microsoft|immersive|subtitle|youtubei\/v1\/player)/i;

const browserCdp = connect(version.webSocketDebuggerUrl);
await browserCdp.ready;

browserCdp.on(async (msg) => {
  if (msg.method === "Target.attachedToTarget") {
    const { sessionId, targetInfo } = msg.params;
    capturedSessions.set(sessionId, targetInfo.url);
    try {
      await browserCdp.send("Network.enable", { maxPostDataSize: 1 << 20 }, sessionId);
    } catch (error) {
      console.error("network enable failed:", targetInfo.url, error.message);
    }
    return;
  }
  if (!msg.sessionId) return;
  const origin = capturedSessions.get(msg.sessionId);
  if (msg.method === "Network.requestWillBeSent") {
    const { requestId, request, initiator, timestamp } = msg.params;
    if (!networkPattern.test(request.url)) return;
    const record = {
      requestId,
      ts: timestamp,
      method: request.method,
      url: request.url,
      origin,
      initiator: initiator?.type,
      initiatorUrl: initiator?.url,
      postData: request.postData ? request.postData.slice(0, 4000) : undefined,
    };
    network.push(record);
    networkById.set(`${msg.sessionId}:${requestId}`, record);
  } else if (msg.method === "Network.responseReceived") {
    const record = networkById.get(`${msg.sessionId}:${msg.params.requestId}`);
    if (!record) return;
    record.status = msg.params.response.status;
    record.mimeType = msg.params.response.mimeType;
    record.fromDiskCache = msg.params.response.fromDiskCache;
    record.fromServiceWorker = msg.params.response.fromServiceWorker;
  } else if (msg.method === "Network.loadingFinished") {
    const key = `${msg.sessionId}:${msg.params.requestId}`;
    const record = networkById.get(key);
    if (!record) return;
    record.encodedDataLength = msg.params.encodedDataLength;
    if (!record.status || record.status >= 400) return;
    try {
      const body = await browserCdp.send(
        "Network.getResponseBody",
        { requestId: msg.params.requestId },
        msg.sessionId
      );
      record.responseBody = body.base64Encoded
        ? Buffer.from(body.body, "base64").toString("utf8").slice(0, 4000)
        : body.body.slice(0, 4000);
    } catch {
      // Service workers can drop a body before CDP asks for it; the request
      // record alone still proves the call path.
    }
  }
});

await browserCdp.send("Target.setDiscoverTargets", { discover: true });
browserCdp.on(async (msg) => {
  if (msg.method !== "Target.targetCreated") return;
  const info = msg.params.targetInfo;
  const isExtensionContext =
    info.url.startsWith(`chrome-extension://${EXT_ID}`) ||
    info.url.startsWith(`chrome-extension://${EXT_ID}/`) ||
    (info.type === "service_worker" && info.url.includes(EXT_ID));
  if (!isExtensionContext) return;
  try {
    await browserCdp.send("Target.attachToTarget", {
      targetId: info.targetId,
      flatten: true,
    });
  } catch (error) {
    console.error("attach failed:", info.url, error.message);
  }
});
// Discover already-running contexts: setDiscoverTargets replays targetCreated
// for existing targets, but re-issue explicitly in case the worker started
// before the listener was installed.
for (const target of targets) {
  if (!target.url.startsWith(`chrome-extension://${EXT_ID}`)) continue;
  try {
    await browserCdp.send("Target.attachToTarget", {
      targetId: target.id,
      flatten: true,
    });
  } catch (error) {
    console.error("attach failed:", target.url, error.message);
  }
}

// ---------------------------------------------------------------------------
// Drive the player and sample the caption window.
// ---------------------------------------------------------------------------
await send("Page.enable");
await send("Page.bringToFront");
try {
  const { windowId } = await send("Browser.getWindowForTarget", {
    targetId: page.id,
  });
  await send("Browser.setWindowBounds", {
    windowId,
    bounds: { windowState: "normal" },
  });
  await send("Browser.setWindowBounds", {
    windowId,
    bounds: { windowState: "maximized" },
  });
} catch (error) {
  console.error("window restore skipped:", error.message);
}
await send("Page.setWebLifecycleState", { state: "active" });
await send("Emulation.setFocusEmulationEnabled", { enabled: true }).catch(() => {});

const seek = await evalPage(`(async () => {
  const v = document.querySelector('video');
  if (!v) return { error: 'no video' };
  v.currentTime = ${startAt};
  await new Promise((resolve) => {
    if (!v.seeking) return resolve();
    v.addEventListener('seeked', resolve, { once: true });
    setTimeout(resolve, 8000);
  });
  try { await v.play(); } catch (e) {}
  return { currentTime: v.currentTime, duration: v.duration, paused: v.paused };
})()`);

const sampleExpr = `(() => {
  const v = document.querySelector('video');
  const host = document.querySelector('#immersive-translate-caption-window');
  const sr = host && host.shadowRoot;
  const cues = sr ? [...sr.querySelectorAll('.imt-cue')] : [];
  const pick = (cls) => cues.filter(c => c.classList.contains(cls)).map(c => c.innerText.trim()).join(' | ');
  return {
    t: v ? Number(v.currentTime.toFixed(3)) : null,
    paused: v ? v.paused : null,
    src: pick('source-cue'),
    tgt: pick('target-cue'),
    loading: pick('loading-text'),
    native: [...document.querySelectorAll('.ytp-caption-segment')].map(e => e.innerText.trim()).join(' | '),
  };
})()`;

const started = Date.now();
const samples = [];
const events = [];
let lastKey = null;
while (Date.now() - started < duration * 1000) {
  const value = await evalPage(sampleExpr);
  const key = `${value.src}\u0000${value.tgt}`;
  if (key !== lastKey) {
    events.push({ wall: new Date().toISOString(), ...value });
    lastKey = key;
  }
  samples.push(value);
  await new Promise((r) => setTimeout(r, 120));
}

const summary = {
  videoUrl: page.url,
  extensionId: EXT_ID,
  startAt,
  duration,
  capturedSamples: samples.length,
  extensionContexts: [...new Set(capturedSessions.values())],
  events,
  network,
};
fs.writeFileSync(outFile, JSON.stringify(summary, null, 2), "utf8");
console.log(
  "events",
  events.length,
  "samples",
  samples.length,
  "network",
  network.length,
  "->",
  outFile
);
pageCdp.ws.close();
browserCdp.ws.close();

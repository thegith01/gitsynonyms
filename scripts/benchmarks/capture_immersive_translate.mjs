// Capture Immersive Translate's live subtitle behavior for a time window.
//
// Usage:
//   node scripts/benchmarks/capture_immersive_translate.mjs 300 90 capture_300.json
//
// Requires Chrome started with --remote-debugging-port=9222 (or CDP_PORT), a
// youtube.com/watch page, and the Immersive Translate extension enabled. The
// output is temporary evidence; commit conclusions to observed-YYYY-MM-DD.json,
// not the capture file.
import fs from "node:fs";

const PORT = process.env.CDP_PORT || "9222";
const BASE = `http://127.0.0.1:${PORT}`;
const startAt = Number(process.argv[2] || 300);
const duration = Number(process.argv[3] || 90);
const outFile = process.argv[4] || "capture.json";

const targets = await (await fetch(`${BASE}/json/list`)).json();
const page = targets.find((t) => t.type === "page" && t.url.includes("youtube.com/watch"));
if (!page) throw new Error("no youtube page");

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => {
  ws.addEventListener("open", res, { once: true });
  ws.addEventListener("error", rej, { once: true });
});
let id = 0;
const pending = new Map();
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(JSON.stringify(msg.error)));
    else resolve(msg.result);
  }
});
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const myId = ++id;
    pending.set(myId, { resolve, reject });
    ws.send(JSON.stringify({ id: myId, method, params }));
  });

// Capture the requests that reveal the extension's real pipeline. YouTube's
// timedtext responses are the source phrases; translation-host requests show
// which engine receives the visible window. The extension may issue these from
// the page context (content script), so they appear on the page target.
const network = [];
const networkById = new Map();
const networkPattern =
  /(timedtext|translate|cognitive|bing|googleapis|microsoft|immersive|subtitle)/i;
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.method === "Network.requestWillBeSent") {
    const { requestId, request, initiator, timestamp } = msg.params;
    if (!networkPattern.test(request.url)) return;
    const record = {
      requestId,
      ts: timestamp,
      method: request.method,
      url: request.url,
      initiator: initiator?.type,
      initiatorUrl: initiator?.url,
      postData: request.postData ? request.postData.slice(0, 2000) : undefined,
    };
    network.push(record);
    networkById.set(requestId, record);
  } else if (msg.method === "Network.responseReceived") {
    const record = networkById.get(msg.params.requestId);
    if (!record) return;
    record.status = msg.params.response.status;
    record.mimeType = msg.params.response.mimeType;
    record.fromDiskCache = msg.params.response.fromDiskCache;
    record.fromServiceWorker = msg.params.response.fromServiceWorker;
  } else if (msg.method === "Network.loadingFinished") {
    const record = networkById.get(msg.params.requestId);
    if (record) record.encodedDataLength = msg.params.encodedDataLength;
  }
});
const evalPage = async (expression) => {
  const res = await send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (res.exceptionDetails) throw new Error(res.exceptionDetails.text || "eval failed");
  return res.result.value;
};

await send("Page.enable");
await send("Network.enable", { maxPostDataSize: 65536 });
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
    setTimeout(resolve, 5000);
  });
  try { await v.play(); } catch (e) {}
  return { currentTime: v.currentTime, duration: v.duration };
})()`);
console.log("seek", JSON.stringify(seek));

const sampleExpr = `(() => {
  const v = document.querySelector('video');
  const host = document.querySelector('#immersive-translate-caption-window');
  const sr = host && host.shadowRoot;
  const container = sr && sr.querySelector('.imt-caption-container');
  const cues = sr ? [...sr.querySelectorAll('.imt-cue')] : [];
  const src = cues.filter(c => c.classList.contains('source-cue')).map(c => c.innerText.trim()).join(' | ');
  const tgt = cues.filter(c => c.classList.contains('target-cue')).map(c => c.innerText.trim()).join(' | ');
  const loading = cues.filter(c => c.classList.contains('loading-text')).map(c => c.innerText.trim()).join(' | ');
  const native = [...document.querySelectorAll('.ytp-caption-segment')].map(e => e.innerText.trim()).join(' | ');
  return {
    t: v ? Number(v.currentTime.toFixed(3)) : null,
    paused: v ? v.paused : null,
    vis: document.visibilityState,
    cc: document.querySelector('.ytp-subtitles-button')?.getAttribute('aria-pressed'),
    hasContainer: !!container,
    src, tgt, loading,
    native,
  };
})()`;

const started = Date.now();
let lastKey = null;
const samples = [];
const events = [];
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
  startAt,
  duration,
  capturedSamples: samples.length,
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
ws.close();

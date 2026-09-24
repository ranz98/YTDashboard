"use strict";

// Launched by run.bat as chrome-extension://<id>/trigger.html?channel=@Handle
//
// This is an extension page, not a web page: it always loads, nothing can
// redirect it or strip its query string, and it can message the service worker
// directly instead of hoping a tabs event wakes it.

const params = new URLSearchParams(location.search);
const channel = params.get("channel") || "@Clips_Edge";

const logEl = document.getElementById("log");
document.getElementById("target").textContent = `channel ${channel}`;

function line(text, cls = "") {
  const now = new Date().toLocaleTimeString();
  const el = document.createElement("div");
  el.className = "line";
  el.innerHTML = `<span class="t">${now}</span><span class="${cls}"></span>`;
  el.lastChild.textContent = text;
  logEl.appendChild(el);
  window.scrollTo(0, document.body.scrollHeight);
}

// The worker publishes each stage to storage; mirror it here as it happens.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || !changes.progress) return;
  const p = changes.progress.newValue;
  if (p?.message) line(p.message);
});

(async () => {
  line(`Asking the worker to grab the newest Short from ${channel}`);
  try {
    const res = await chrome.runtime.sendMessage({ type: "grab", channel });
    if (!res) throw new Error("No response from the service worker.");
    if (!res.ok) throw new Error(res.error || "Grab failed.");

    if (res.isNew) {
      line(`NEW: ${res.entry.title || "Untitled Short"}`, "ok");
      line(`Saved to ${res.savedTo}`, "ok");
    } else {
      const when = res.previous
        ? new Date(res.previous.capturedAt).toLocaleString()
        : "an earlier run";
      line(`No new Shorts. The newest was already captured (${when}).`, "dim");
      line(`Nothing was added to the log.`, "dim");
    }

    const a = document.createElement("a");
    a.className = "url";
    a.href = res.entry.url;
    a.textContent = res.entry.url;
    a.target = "_blank";
    logEl.appendChild(a);
  } catch (err) {
    line(`FAILED: ${err?.message || err}`, "err");
    line("run.bat will print this too. Full log: chrome://extensions -> service worker.", "err");
  }
})();

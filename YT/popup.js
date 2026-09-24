"use strict";

// Thin client: the service worker does the work, the popup just drives it and
// puts the resulting URL on the clipboard (service workers cannot).

const DEFAULT_HANDLE = "@Clips_Edge";

const el = {
  channel: document.getElementById("channel"),
  go: document.getElementById("go"),
  status: document.getElementById("status"),
  result: document.getElementById("result"),
  resultTitle: document.getElementById("result-title"),
  resultUrl: document.getElementById("result-url"),
  savedTo: document.getElementById("saved-to"),
  fallback: document.getElementById("clipboard-fallback"),
};

function setStatus(message, kind = "") {
  el.status.textContent = message;
  el.status.className = kind;
}

function showResult(entry, prefix = "") {
  el.resultTitle.textContent = prefix + (entry.title || "Untitled Short");
  el.resultUrl.textContent = entry.url;
  el.resultUrl.href = entry.url;
  el.result.classList.add("show");
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for when the popup does not hold focus.
    el.fallback.value = text;
    el.fallback.select();
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    }
  }
}

async function run() {
  el.go.disabled = true;
  el.result.classList.remove("show");
  el.savedTo.textContent = "";
  setStatus("Opening the channel and looking for the first Short…");

  try {
    const channel = el.channel.value.trim();
    const res = await chrome.runtime.sendMessage({ type: "grab", channel });
    if (!res) throw new Error("The extension's background worker did not respond.");
    if (!res.ok) throw new Error(res.error || "Grab failed.");

    const copied = await copyToClipboard(res.entry.url);
    showResult(res.entry, res.isNew ? "" : "Already had: ");

    if (res.isNew) {
      el.savedTo.textContent = `Saved to ${res.savedTo}`;
      setStatus(
        copied ? "New Short - copied and saved." : "New Short saved. Copy the URL above manually.",
        copied ? "ok" : "err"
      );
    } else {
      const when = res.previous
        ? new Date(res.previous.capturedAt).toLocaleString()
        : "an earlier run";
      el.savedTo.textContent = `First seen ${when}. Log unchanged.`;
      setStatus(copied ? "No new Shorts. URL copied anyway." : "No new Shorts.", "");
    }
  } catch (err) {
    setStatus(String(err?.message || err), "err");
  } finally {
    el.go.disabled = false;
  }
}

(async () => {
  const { channel, last } = await chrome.storage.local.get(["channel", "last"]);
  el.channel.value = channel || DEFAULT_HANDLE;
  if (last) showResult(last, "Last: ");
})();

el.go.addEventListener("click", run);
el.channel.addEventListener("keydown", (e) => {
  if (e.key === "Enter") run();
});

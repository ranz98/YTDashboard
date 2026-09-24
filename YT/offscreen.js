"use strict";

// Fallback path only. The service worker has no URL.createObjectURL, so if a
// data: URL download is rejected it asks this document to mint a blob URL.

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.target !== "offscreen") return;

  if (msg.type === "make-blob-url") {
    const url = URL.createObjectURL(new Blob([msg.text], { type: "text/plain" }));
    sendResponse({ url });
    return true;
  }

  if (msg.type === "revoke-blob-url") {
    URL.revokeObjectURL(msg.url);
    sendResponse({ ok: true });
    return true;
  }
});

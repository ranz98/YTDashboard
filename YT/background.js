"use strict";

/**
 * Service worker: finds the newest Short on a channel, opens it, and writes
 * the URL to text files in Chrome's download folder.
 *
 * Two ways in:
 *   1. run.bat opens a channel Shorts URL carrying ?ytgrab=1. That marker is
 *      the trigger, so it works whether Chrome was cold-started or already
 *      running -- unlike runtime.onStartup, which only fires on a cold start.
 *   2. The toolbar popup, for a manual re-run.
 */

const DEFAULT_HANDLE = "@Clips_Edge";
const TRIGGER_PARAM = "ytgrab";
const LATEST_FILE = "latest-short.txt";
const LOG_FILE = "shorts-log.txt";
const ERROR_FILE = "error.txt";
const NONEW_FILE = "no-new.txt";
const TITLE_FILE = "latest-title.txt";
const MAX_HISTORY = 500;
// Kept far longer than the history so a Short cannot age out of the seen set
// and get re-reported as new.
const MAX_SEEN = 5000;

const SCRAPE_ATTEMPTS = 4;
const SCRAPE_TIMEOUT_MS = 20000;
const GRAB_TIMEOUT_MS = 120000;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Entries written before v1.4 have no id field; recover it from the URL so an
// existing history still counts as already-seen.
function idOf(entry) {
  if (entry?.id) return entry.id;
  const m = /\/shorts\/([A-Za-z0-9_-]+)/.exec(entry?.url || "");
  return m ? m[1] : null;
}

// Every stage is published to storage so trigger.html can mirror it live, and
// echoed to the worker console for chrome://extensions.
function report(message) {
  console.log("[First Short Grabber]", message);
  return chrome.storage.local.set({ progress: { message, at: Date.now() } });
}

// Nothing here may hang. YouTube can navigate the page out from under an
// injected script, and executeScript then never settles -- neither resolving
// nor rejecting. Without this the whole worker parks forever.
function withTimeout(promise, ms, label) {
  let timer;
  const bell = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms / 1000}s.`)), ms);
  });
  return Promise.race([promise, bell]).finally(() => clearTimeout(timer));
}

// A service worker is killed after ~30s with no extension API calls, which a
// long scrape can easily exceed. Any API call resets that timer.
function keepAlive() {
  const id = setInterval(() => chrome.runtime.getPlatformInfo().catch(() => {}), 20000);
  return () => clearInterval(id);
}

/* ---------- channel parsing ---------- */

// Accepts "@Handle", "Handle", or any youtube.com channel URL.
function parseChannel(raw) {
  const input = (raw || "").trim();
  if (!input) throw new Error("Enter a channel handle or URL.");

  if (/^https?:\/\//i.test(input)) {
    let url;
    try {
      url = new URL(input);
    } catch {
      throw new Error("That does not look like a valid URL.");
    }
    if (!/(^|\.)youtube\.com$/i.test(url.hostname)) {
      throw new Error("Only youtube.com channel URLs are supported.");
    }
    const path = url.pathname.replace(/\/+$/, "");
    const m = path.match(/^\/(@[^/]+|c\/[^/]+|user\/[^/]+|channel\/[^/]+)/);
    if (!m) throw new Error("Could not find a channel in that URL.");
    return {
      handle: m[1].startsWith("@") ? m[1] : m[1].split("/").pop(),
      shortsUrl: `https://www.youtube.com/${m[1]}/shorts`,
    };
  }

  const handle = input.startsWith("@") ? input : `@${input}`;
  if (!/^@[A-Za-z0-9._-]+$/.test(handle)) {
    throw new Error("That handle contains unsupported characters.");
  }
  return { handle, shortsUrl: `https://www.youtube.com/${handle}/shorts` };
}

/* ---------- injected page scraper ---------- */

// Runs inside the YouTube tab. Polls until the Shorts grid renders, then
// returns the first Short in DOM order.
async function scrapeFirstShort() {
  // Short per-attempt budget: the caller retries, and a long single call risks
  // the service worker being idle-killed while it waits.
  const ID_RE = /\/shorts\/([A-Za-z0-9_-]{6,})/;
  const DEADLINE = Date.now() + 12000;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const titleFor = (anchor) => {
    const card =
      anchor.closest("ytm-shorts-lockup-view-model") ||
      anchor.closest("ytd-rich-item-renderer") ||
      anchor.closest("ytd-reel-item-renderer") ||
      anchor;
    const label =
      anchor.getAttribute("title") ||
      anchor.getAttribute("aria-label") ||
      card.querySelector("h3, [class*=MetadataTitle], #video-title")?.textContent ||
      "";
    return label.replace(/\s+/g, " ").trim().slice(0, 200);
  };

  const pick = () => {
    // Prefer the grid so we never match the sidebar's Shorts nav entry.
    const scopes = [
      document.querySelector("ytd-rich-grid-renderer #contents"),
      document.querySelector("ytd-two-column-browse-results-renderer #contents"),
      document.body,
    ].filter(Boolean);

    for (const scope of scopes) {
      for (const a of scope.querySelectorAll('a[href*="/shorts/"]')) {
        const m = ID_RE.exec(a.getAttribute("href") || "");
        if (!m) continue;
        // Skip anything not actually laid out (hidden templates, stubs).
        if (!a.getClientRects().length) continue;
        return { id: m[1], title: titleFor(a) };
      }
    }
    return null;
  };

  while (Date.now() < DEADLINE) {
    const hit = pick();
    if (hit) return { ok: true, ...hit };
    await sleep(300);
  }

  const blocked =
    /consent|sorry/i.test(location.hostname + location.pathname) ||
    /before you continue/i.test(document.body.innerText.slice(0, 400));
  return {
    ok: false,
    reason: blocked
      ? "YouTube showed a consent or sign-in wall instead of the channel."
      : "No Shorts appeared on that page in time.",
  };
}

/* ---------- tabs ---------- */

async function waitForLoad(tabId, timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") return tab;
    await sleep(200);
  }
  throw new Error("The YouTube tab took too long to load.");
}

// YouTube reloads the page on the first visit in a fresh profile (it appends
// themeRefresh=1), destroying any script injected into the previous frame --
// executeScript then hangs rather than failing. One attempt is never enough.
async function scrapeWithRetries(tabId) {
  let lastErr = new Error("Could not read the channel page.");

  for (let attempt = 1; attempt <= SCRAPE_ATTEMPTS; attempt++) {
    try {
      await report(`Reading the Shorts grid (attempt ${attempt} of ${SCRAPE_ATTEMPTS})`);
      await waitForLoad(tabId);
      const injected = await withTimeout(
        chrome.scripting.executeScript({ target: { tabId }, func: scrapeFirstShort }),
        SCRAPE_TIMEOUT_MS,
        `Scrape attempt ${attempt}`
      );
      const result = injected?.[0]?.result;
      if (result?.ok) return result;
      lastErr = new Error(result?.reason || "Could not read the channel page.");
    } catch (err) {
      lastErr = err instanceof Error ? err : new Error(String(err));
      await report(`Attempt ${attempt} failed: ${lastErr.message}`);
    }
    if (attempt < SCRAPE_ATTEMPTS) await sleep(2000); // let any redirect settle
  }

  throw lastErr;
}

/* ---------- file output ---------- */

// Service workers have no URL.createObjectURL, so an offscreen document is the
// only way to mint a blob URL. Data URLs normally work and need no offscreen
// document at all, so try that first and fall back if Chrome rejects it.
async function blobUrlViaOffscreen(text) {
  if (!(await chrome.offscreen.hasDocument())) {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["BLOBS"],
      justification: "Create a blob URL to write the captured Short URL to a text file.",
    });
  }
  const res = await chrome.runtime.sendMessage({
    target: "offscreen",
    type: "make-blob-url",
    text,
  });
  if (!res?.url) throw new Error("Offscreen document did not return a blob URL.");
  return res.url;
}

async function startDownload(url, filename) {
  try {
    return await chrome.downloads.download({
      url,
      filename,
      conflictAction: "overwrite",
      saveAs: false,
    });
  } catch {
    // Some setups refuse overwrite (file locked by another app, policy).
    return await chrome.downloads.download({
      url,
      filename,
      conflictAction: "uniquify",
      saveAs: false,
    });
  }
}

async function writeTextFile(filename, text) {
  let blobUrl = null;
  let downloadId;
  try {
    downloadId = await startDownload(
      "data:text/plain;charset=utf-8," + encodeURIComponent(text),
      filename
    );
  } catch (dataUrlErr) {
    console.warn("[First Short Grabber] data: URL download rejected, using offscreen blob", dataUrlErr);
    blobUrl = await blobUrlViaOffscreen(text);
    downloadId = await startDownload(blobUrl, filename);
  }

  // run.bat polls for the finished file, so wait for a terminal state.
  await new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      chrome.downloads.onChanged.removeListener(onChanged);
      resolve();
    };
    const onChanged = (delta) => {
      if (delta.id === downloadId && delta.state?.current !== "in_progress") finish();
    };
    const timer = setTimeout(finish, 10000);
    chrome.downloads.onChanged.addListener(onChanged);
    chrome.downloads.search({ id: downloadId }).then((items) => {
      if (items[0] && items[0].state !== "in_progress") finish();
    });
  });

  if (blobUrl) {
    await chrome.runtime
      .sendMessage({ target: "offscreen", type: "revoke-blob-url", url: blobUrl })
      .catch(() => {});
  }

  const [item] = await chrome.downloads.search({ id: downloadId });
  if (item && item.state === "interrupted") {
    throw new Error(`Could not write ${filename} (${item.error || "download interrupted"}).`);
  }
  return item?.filename || filename;
}

// run.bat waits on LATEST_FILE, so it is always written last -- by the time it
// appears, every other file for this run is already on disk.
async function saveOutput(entry, history) {
  await report(`Writing ${LOG_FILE} and ${LATEST_FILE}`);

  const log = [
    "# Every new Short captured, most recent first. Repeats are not re-logged.",
    `# Updated ${new Date().toLocaleString()}`,
    "",
    ...history.map(
      (e) =>
        `${new Date(e.capturedAt).toLocaleString()}\t${e.channel}\t${e.url}\t${e.title || ""}`
    ),
    "",
  ].join("\r\n");
  await writeTextFile(LOG_FILE, log);

  // The Short's own title, for the rewrite stage downstream.
  await writeTextFile(TITLE_FILE, (entry.title || "") + "\r\n");

  // Bare URL on one line -- what run.bat reads and pipes to the clipboard.
  return writeTextFile(LATEST_FILE, entry.url + "\r\n");
}

// Nothing new. The marker goes down first so run.bat, which wakes on
// LATEST_FILE, always finds it already in place.
async function saveUnchanged(entry, previous) {
  await report(`Writing ${NONEW_FILE}`);
  await writeTextFile(
    NONEW_FILE,
    [
      "No new Shorts - the newest one was already captured.",
      `Checked    : ${new Date().toLocaleString()}`,
      `Channel    : ${entry.channel}`,
      `Newest     : ${entry.url}`,
      `Title      : ${entry.title || "(untitled)"}`,
      previous
        ? `First seen : ${new Date(previous.capturedAt).toLocaleString()}`
        : "First seen : an earlier run",
      "",
    ].join("\r\n")
  );

  await writeTextFile(TITLE_FILE, (entry.title || "") + "\r\n");

  // Still refresh this so the clipboard gets the current newest URL either way.
  return writeTextFile(LATEST_FILE, entry.url + "\r\n");
}

/* ---------- main flow ---------- */

// Grabs run one at a time, so a popup click landing during a triggered run
// waits its turn instead of racing it. Every link in the chain is timeout-
// guarded: one stuck grab must never wedge the queue for the whole session.
let queue = Promise.resolve();

function grabFirstShort(opts) {
  const next = queue.then(async () => {
    // Outside the race, not inside runGrab: if runGrab hangs past the timeout
    // its own finally never runs, and the interval would pin the worker alive
    // forever.
    const stopKeepAlive = keepAlive();
    try {
      return await withTimeout(runGrab(opts), GRAB_TIMEOUT_MS, "Grab");
    } catch (err) {
      // Here rather than in one caller, so a failure reaches error.txt no
      // matter which entry point started the grab.
      await recordFailure(opts, err);
      throw err;
    } finally {
      stopKeepAlive();
    }
  });
  queue = next.catch(() => {});
  return next;
}

async function recordFailure(opts, err) {
  const message = String(err?.message || err);
  console.error("[First Short Grabber]", err);
  await report(`FAILED: ${message}`).catch(() => {});
  await chrome.storage.local
    .set({ lastError: { message, at: Date.now() } })
    .catch(() => {});

  // run.bat watches for this file, so a failure surfaces as a message in the
  // terminal instead of a silent timeout.
  await writeTextFile(
    ERROR_FILE,
    [
      "First Short Grabber failed.",
      `When    : ${new Date().toLocaleString()}`,
      `Channel : ${opts?.channel || "(unknown)"}`,
      `Reason  : ${message}`,
      "",
      "Open chrome://extensions in this profile and click the extension's",
      "service worker link for the full console log.",
      "",
    ].join("\r\n")
  ).catch((e) => console.error("[First Short Grabber] could not write error file", e));
}

async function runGrab({ channel, tabId = null }) {
  const { handle, shortsUrl } = parseChannel(channel);
  await chrome.storage.local.set({ channel: handle });

  // Reuse the trigger tab when one was supplied; otherwise open our own.
  let targetId = tabId;
  if (targetId == null) {
    await report(`Opening ${shortsUrl}`);
    const tab = await chrome.tabs.create({ url: shortsUrl, active: true });
    targetId = tab.id;
  } else {
    await report(`Using the tab already on ${handle}'s Shorts`);
  }

  const result = await scrapeWithRetries(targetId);
  await report(`Newest Short is ${result.id} - ${result.title || "untitled"}`);

  const entry = {
    id: result.id,
    url: `https://www.youtube.com/shorts/${result.id}`,
    title: result.title,
    channel: handle,
    capturedAt: Date.now(),
  };

  const store = await chrome.storage.local.get(["history", "seenIds"]);
  const history = store.history || [];
  // No seenIds yet means a pre-v1.4 profile: seed the set from the history so
  // an upgrade does not re-announce Shorts that were already captured.
  const seen = store.seenIds || history.map(idOf).filter(Boolean);

  if (seen.includes(result.id)) {
    const previous = history.find((e) => idOf(e) === result.id);
    const when = previous ? new Date(previous.capturedAt).toLocaleString() : "an earlier run";
    await report(`Already captured (${when}) - nothing new`);
    const savedTo = await saveUnchanged(entry, previous);
    return { ok: true, isNew: false, entry, previous, savedTo };
  }

  await report("This one is new - opening it");
  await chrome.tabs.update(targetId, { url: entry.url, active: true });

  const updatedHistory = [entry, ...history].slice(0, MAX_HISTORY);
  const updatedSeen = [result.id, ...seen].slice(0, MAX_SEEN);
  await chrome.storage.local.set({
    history: updatedHistory,
    seenIds: updatedSeen,
    last: entry,
  });

  const savedTo = await saveOutput(entry, updatedHistory);
  return { ok: true, isNew: true, entry, savedTo };
}

/* ---------- trigger: a channel Shorts URL carrying ?ytgrab=1 ---------- */

const handled = new Set();

// Claim a tab so the onUpdated listener and the startup sweep cannot both act
// on it. Check and add are synchronous on purpose. A claim is released as soon
// as the grab settles -- holding it through a failure would swallow the retry
// that YouTube's own redirect triggers.
function claim(tabId) {
  if (handled.has(tabId)) return false;
  handled.add(tabId);
  return true;
}

function release(tabId) {
  handled.delete(tabId);
}

function isTrigger(rawUrl) {
  let url;
  try {
    url = new URL(rawUrl || "");
  } catch {
    return false;
  }
  return (
    /(^|\.)youtube\.com$/i.test(url.hostname) &&
    url.searchParams.get(TRIGGER_PARAM) === "1"
  );
}

async function runTrigger(tab) {
  try {
    // grabFirstShort already records the failure; swallow so the event
    // listener does not raise an unhandled rejection.
    await grabFirstShort({ channel: tab.url, tabId: tab.id });
  } catch {
    /* recorded in recordFailure */
  } finally {
    // Let YouTube's redirect, or the next sweep, have another go at this tab.
    release(tab.id);
  }
}

// On a cold Chrome start the tab can finish loading before this worker wakes,
// so onUpdated alone would miss it. Sweep any already-open trigger tabs too.
// Safe to repeat: a grabbed tab is navigated to the Short, dropping the marker.
async function sweepTriggerTabs() {
  const tabs = await chrome.tabs.query({ url: "*://*.youtube.com/*" });
  for (const tab of tabs) {
    if (!isTrigger(tab.url) || !claim(tab.id)) continue;
    await runTrigger(tab);
    break;
  }
}

chrome.runtime.onStartup.addListener(() => {
  sweepTriggerTabs().catch((e) => console.error("[First Short Grabber]", e));
});
sweepTriggerTabs().catch(() => {});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete") return;
  if (!isTrigger(tab.url) || !claim(tabId)) return;
  await runTrigger(tab);
});

/* ---------- popup bridge ---------- */

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type !== "grab") return;
  grabFirstShort({ channel: msg.channel })
    .then(sendResponse)
    .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));
  return true; // keep the channel open for the async reply
});

chrome.runtime.onInstalled.addListener(async () => {
  const { channel } = await chrome.storage.local.get("channel");
  if (!channel) await chrome.storage.local.set({ channel: DEFAULT_HANDLE });
});

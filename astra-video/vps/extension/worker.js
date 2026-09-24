'use strict';
let busy = false;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function bridge(path, value) {
  const {token} = await chrome.storage.local.get('token');
  if (!token) throw new Error('Pair the extension first.');
  const response = await fetch('http://127.0.0.1:18765' + path, {
    method: value ? 'POST' : 'GET',
    headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
    body: value ? JSON.stringify(value) : undefined,
    signal: AbortSignal.timeout(10000)
  });
  if (!response.ok) throw new Error('Local bridge rejected the request: ' + response.status);
  return response.json();
}

// Keep DOM access in the tab; the service worker owns orchestration.
function page(action, value) {
  const visible = element => element && element.getClientRects().length &&
    !element.disabled && element.getAttribute('aria-disabled') !== 'true';
  const select = selector => [...document.querySelectorAll(selector)].find(visible);
  if (action === 'scan') {
    for (const media of document.querySelectorAll('video,audio')) {
      media.pause(); media.autoplay = false; media.preload = 'none';
    }
    const videos = [], seen = new Set();
    for (const anchor of document.querySelectorAll('a[href*="/shorts/"]')) {
      const id = anchor.getAttribute('href').match(/\/shorts\/([\w-]{11})(?:[/?]|$)/)?.[1];
      if (!id || seen.has(id)) continue;
      seen.add(id);
      const card = anchor.closest('ytd-rich-item-renderer, ytd-reel-item-renderer, yt-lockup-view-model') || anchor;
      const title = card.querySelector('[title]')?.getAttribute('title') || anchor.getAttribute('aria-label') || card.innerText || id;
      videos.push({id, title: title.trim()});
      if (videos.length === 5) break;
    }
    return videos;
  }
  if (action === 'channel') return location.pathname.match(/^\/channel\/(UC[\w-]{22})(?:\/|$)/)?.[1] || '';
  if (action === 'open-upload') {
    if (document.querySelector('input[type=file]')) return true;
    const upload = select('#upload-icon') || select('ytcp-button#upload-button');
    if (upload) { upload.click(); return false; }
    const create = select('#create-icon');
    if (create) create.click();
    const menu = [...document.querySelectorAll('tp-yt-paper-item, ytcp-ve')].find(e => visible(e) && e.textContent.trim() === 'Upload videos');
    if (menu) menu.click();
    return false;
  }
  if (action === 'details') {
    const title = select('ytcp-social-suggestions-textbox#title-textarea #textbox');
    if (!title) return false;
    title.focus(); title.textContent = value;
    title.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
    title.dispatchEvent(new Event('change', {bubbles: true}));
    const audience = select('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]');
    if (!audience) return false;
    audience.click();
    return title.textContent.trim() === value;
  }
  if (action === 'next') {
    if (select('tp-yt-paper-radio-button[name="PUBLIC"]')) return 'visibility';
    const next = select('#next-button');
    if (next) { next.click(); return 'next'; }
    return 'waiting';
  }
  if (action === 'public') {
    const radio = select('tp-yt-paper-radio-button[name="PUBLIC"]');
    if (!radio) return false;
    radio.click();
    return radio.getAttribute('aria-checked') === 'true' || radio.hasAttribute('checked');
  }
  if (action === 'publish-ready') {
    const button = select('#done-button');
    const radio = select('tp-yt-paper-radio-button[name="PUBLIC"]');
    return Boolean(button && /publish/i.test(button.innerText) && radio &&
      (radio.getAttribute('aria-checked') === 'true' || radio.hasAttribute('checked')));
  }
  if (action === 'publish') {
    const button = select('#done-button');
    if (!button || !/publish/i.test(button.innerText)) throw new Error('Publish button is not ready.');
    button.click(); return true;
  }
  if (action === 'confirmation') {
    const dialog = select('ytcp-video-share-dialog');
    if (!dialog || !/video published/i.test(dialog.innerText)) return null;
    const links = [...dialog.querySelectorAll('a[href]')].map(a => a.href).join(' ');
    const id = (links + ' ' + dialog.innerText).match(/(?:youtu\.be\/|youtube\.com\/watch\?v=)([\w-]{11})/)?.[1];
    return id || null;
  }
  throw new Error('Unknown tab operation.');
}

async function inTab(tabId, action, value) {
  const [result] = await chrome.scripting.executeScript({target: {tabId}, func: page, args: [action, value ?? null]});
  return result.result;
}

async function checkpoint(command) {
  const current = (await bridge('/command')).command;
  if (!current || current.id !== command.id || current.cancel) throw new Error('Operation stopped.');
}

async function until(command, operation, milliseconds = 120000, interval = 3000) {
  const end = Date.now() + milliseconds;
  while (Date.now() < end) {
    await checkpoint(command);
    const result = await operation();
    if (result) return result;
    await sleep(interval);
  }
  throw new Error('YouTube did not reach the expected screen. Review the VPS log.');
}

async function finish(active, result) {
  const reviewUpload = active.action === 'upload' && !result.ok;
  if (active.tabId && reviewUpload) {
    // Leave uncertain uploads visible for reconciliation; never submit them again.
    try { await chrome.debugger.detach({tabId: active.tabId}); } catch (_) {}
  }
  if (active.tabId && !reviewUpload) {
    try { await chrome.tabs.remove(active.tabId); }
    catch (_) {
      // A missing tab is already stopped; other failures must not release the lease.
      const tabs = await chrome.tabs.query({});
      if (tabs.some(tab => tab.id === active.tabId)) throw new Error('Unable to close agent tab.');
    }
  }
  if (active.action === 'fetch') {
    await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds: [1]});
  }
  const receipt = {id: active.id, ...result};
  await chrome.storage.local.set({receipt});
  await chrome.storage.local.remove('active');
  await bridge('/result', receipt);
}

async function execute(command) {
  let active = {id: command.id, action: command.action};
  await chrome.storage.local.set({active});
  try {
    if (!['fetch', 'upload'].includes(command.action)) throw new Error('Unknown command.');
    if (command.action === 'fetch' && !/^@[\p{L}\p{N}_.-]{2,100}$/u.test(command.handle)) throw new Error('Invalid channel handle.');
    if (command.action === 'upload' && !/^UC[\w-]{22}$/.test(command.destination)) throw new Error('Destination must be a YouTube channel ID.');
    const url = command.action === 'fetch'
      ? 'https://www.youtube.com/' + encodeURIComponent(command.handle) + '/shorts'
      : 'https://studio.youtube.com/channel/' + command.destination;
    const tab = await chrome.tabs.create({url: 'about:blank', active: false});
    active.tabId = tab.id;
    await chrome.storage.local.set({active});
    if (command.action === 'fetch') {
      // Install before navigation; Studio and Python downloads are outside this tab.
      await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds: [1], addRules: [{
        id: 1, priority: 1, action: {type: 'block'},
        condition: {tabIds: [tab.id], resourceTypes: ['image', 'media']}
      }]});
    }
    await chrome.tabs.update(tab.id, {url});
    await chrome.debugger.attach({tabId: tab.id}, '1.3');
    await until(command, async () => (await chrome.tabs.get(tab.id)).status === 'complete');
    if (command.action === 'fetch') {
      let previous = '', stable = 0;
      const videos = await until(command, async () => {
        const found = await inTab(tab.id, 'scan');
        const signature = found.map(video => video.id).join(',');
        stable = signature === previous ? stable + 1 : 0;
        previous = signature;
        return found.length === 5 || (found.length && stable >= 3) ? found : null;
      });
      await finish(active, {ok: true, videos});
      return;
    }
    await until(command, async () => (await inTab(tab.id, 'channel')) === command.destination);
    await until(command, () => inTab(tab.id, 'open-upload'));
    const target = {tabId: tab.id};
    const {root} = await chrome.debugger.sendCommand(target, 'DOM.getDocument', {depth: -1, pierce: true});
    const {nodeId} = await chrome.debugger.sendCommand(target, 'DOM.querySelector', {nodeId: root.nodeId, selector: 'input[type=file]'});
    if (!nodeId) throw new Error('Upload file input was not found.');
    await checkpoint(command);
    await chrome.debugger.sendCommand(target, 'DOM.setFileInputFiles', {nodeId, files: [command.path]});
    await until(command, () => inTab(tab.id, 'details', command.title), 300000);
    await until(command, async () => (await inTab(tab.id, 'next')) === 'visibility', 600000);
    await until(command, () => inTab(tab.id, 'public'));
    await until(command, () => inTab(tab.id, 'publish-ready'), 5400000, 10000);
    await checkpoint(command);
    await inTab(tab.id, 'publish');
    // SD processing can continue after Publish; only a publication receipt completes the task.
    const youtube_id = await until(command, () => inTab(tab.id, 'confirmation'), 5400000, 10000);
    await finish(active, {ok: true, publication_confirmed: true, youtube_id});
  } catch (error) {
    await finish(active, {ok: false, error: String(error.message).slice(0, 400)});
  }
}

async function poll() {
  if (busy) return;
  busy = true;
  try {
    const {command} = await bridge('/command');
    if (!command) return;
    const {active, receipt} = await chrome.storage.local.get(['active', 'receipt']);
    if (receipt?.id === command.id) { await bridge('/result', receipt); return; }
    if (active) {
      // Never repeat a browser action after a service worker restart.
      await finish(active, {ok: false, error: 'Chrome restarted during a task. Review its outcome before retrying.'});
      return;
    }
    if (command.cancel) { await bridge('/result', {id: command.id, ok: false, error: 'Operation stopped.'}); return; }
    await execute(command);
  } catch (error) {
    await chrome.storage.local.set({lastError: String(error.message), lastErrorAt: Date.now()});
  } finally { busy = false; }
}

chrome.alarms.onAlarm.addListener(poll);
chrome.runtime.onStartup.addListener(poll);
chrome.runtime.onInstalled.addListener(() => { chrome.alarms.create('astra', {periodInMinutes: .5}); poll(); });
chrome.runtime.onMessage.addListener((message, sender, respond) => { poll(); respond({ok: true}); });
chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());
chrome.alarms.create('astra', {periodInMinutes: .5});

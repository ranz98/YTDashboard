const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../vps/extension/worker.js'), 'utf8');

function environment(command) {
  const state = {token: 'a'.repeat(64)}, results = [], actions = [], removed = [], rules = [];
  const listener = {addListener() {}};
  const context = vm.createContext({
    setTimeout, clearTimeout, AbortSignal, console,
    fetch: async (url, options) => ({ok: true, json: async () => {
      if (url.endsWith('/result')) { results.push(JSON.parse(options.body)); return {ok: true}; }
      return {command};
    }}),
    chrome: {
      storage: {local: {
        get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(key => [key, state[key]])),
        set: async value => Object.assign(state, value),
        remove: async key => { delete state[key]; }
      }},
      alarms: {create() {}, onAlarm: listener},
      runtime: {onStartup: listener, onInstalled: listener, onMessage: listener},
      action: {onClicked: listener},
      declarativeNetRequest: {updateSessionRules: async value => { rules.push(value); actions.push('rules'); }},
      tabs: {create: async () => ({id: 10}), get: async () => ({status: 'complete'}),
             update: async () => { actions.push('navigate'); },
             remove: async id => removed.push(id), query: async () => []},
      debugger: {attach: async () => {}, sendCommand: async (target, method) => {
        actions.push(method);
        return {root: {nodeId: 1}, nodeId: 2};
      }},
      scripting: {executeScript: async ({args}) => {
        actions.push(args[0]);
        const values = {channel: command.destination, 'open-upload': true, details: true,
          next: 'visibility', public: true, 'publish-ready': true, publish: true,
          confirmation: 'abcdefghijk', scan: Array.from({length: 5}, (_, i) => ({id: 'abcdefghij' + i, title: 'Example'}))};
        return [{result: values[args[0]]}];
      }}
    }
  });
  vm.runInContext(source, context);
  return {context, state, results, actions, removed, rules};
}

(async () => {
  const command = {id: 'one', action: 'upload', destination: 'UC' + 'x'.repeat(22), path: 'C:\\render.mp4', title: 'Title'};
  let env = environment(command);
  await vm.runInContext('poll()', env.context);
  assert.equal(env.results[0].publication_confirmed, true);
  assert.ok(env.actions.indexOf('publish') < env.actions.indexOf('confirmation'));
  assert.deepEqual(env.removed, [10]);
  assert.equal(env.rules.length, 0, 'Studio must not have blocking rules');
  await vm.runInContext('poll()', env.context);
  assert.equal(env.actions.filter(action => action === 'DOM.setFileInputFiles').length, 1);

  env = environment(command);
  env.state.active = {id: 'one', tabId: 10, action: 'upload'};
  await vm.runInContext('poll()', env.context);
  assert.equal(env.results[0].ok, false);
  assert.equal(env.actions.length, 0);
  assert.deepEqual(env.removed, [], 'Uncertain upload stays open for review');

  env = environment({...command, cancel: true});
  await vm.runInContext('poll()', env.context);
  assert.equal(env.actions.length, 0);
  assert.equal(env.results[0].ok, false);

  env = environment({id: 'two', action: 'fetch', handle: '@Example'});
  await vm.runInContext('poll()', env.context);
  assert.equal(env.results[0].videos.length, 5);
  assert.equal(env.actions.includes('DOM.setFileInputFiles'), false);
  assert.deepEqual(Array.from(env.rules[0].addRules[0].condition.tabIds), [10]);
  assert.deepEqual(Array.from(env.rules[0].addRules[0].condition.resourceTypes), ['image', 'media']);
  assert.ok(env.actions.indexOf('rules') < env.actions.indexOf('navigate'));
  assert.deepEqual(Array.from(env.rules.at(-1).removeRuleIds), [1]);
  console.log('Extension checks passed: upload order, receipt replay, restart, cancellation, five-video scan.');
})().catch(error => { console.error(error); process.exit(1); });

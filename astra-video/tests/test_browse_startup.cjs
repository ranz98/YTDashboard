const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
// Filters load before app.js creates the current page.
const context = vm.createContext({document:{addEventListener(){}}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../dashboard/public/assets/browse.js'),'utf8'), context);
assert.equal(vm.runInContext('browseGeneration', context), 0);
assert.equal(vm.runInContext('browseFilters.jobs.stage', context), 'all');
assert.equal(vm.runInContext('browseFilters.uploaded.stage', context), 'uploaded');
console.log('Browse startup passed without app globals.');

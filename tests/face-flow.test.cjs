const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const flow = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../plugin/FaceFlow.js'), 'utf8'), flow);

test('a successful active scan unlocks without a confirmation event', () => {
  const state = flow.transition('idle', 'start');
  assert.equal(flow.mayUnlock(state, true, true), true);
});
test('idle state cannot accept an unsolicited success', () => {
  assert.equal(flow.mayUnlock('idle', true, true), false);
});
test('failed scan or disallowed session cannot unlock', () => {
  assert.equal(flow.mayUnlock('scanning', false, true), false);
  assert.equal(flow.mayUnlock('scanning', true, false), false);
});
test('cancellation invalidates a late PAM success', () => {
  const state = flow.transition('scanning', 'cancel');
  assert.equal(flow.mayUnlock(state, true, true), false);
});

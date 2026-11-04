'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const SourceDiff = require('../static/source-diff.js');

test('a replacement shows the deleted original before the editable new line', () => {
  const {rows, removedTail} = SourceDiff.displayRows('first\nold\nlast', 'first\nnew\nlast');
  assert.deepEqual(rows.map((row) => [row.text, row.added, row.removed]), [
    ['first', false, []], ['new', true, ['old']], ['last', false, []]
  ]);
  assert.deepEqual(removedTail, []);
});

test('deletions at the beginning, middle and end remain visible', () => {
  assert.deepEqual(SourceDiff.displayRows('gone\nfirst', 'first').rows[0].removed, ['gone']);
  assert.deepEqual(SourceDiff.displayRows('a\nremoved\nb', 'a\nb').rows[1].removed, ['removed']);
  assert.deepEqual(SourceDiff.displayRows('a\nlast', 'a').removedTail, ['last']);
});

test('unchanged lines between distant changes are not highlighted', () => {
  const oldText = ['header', ...Array.from({length: 150}, (_, i) => `unique-${i}`), 'footer'].join('\n');
  const newText = ['new header', ...Array.from({length: 150}, (_, i) => `unique-${i}`), 'new footer'].join('\n');
  const result = SourceDiff.displayRows(oldText, newText);
  assert.equal(result.rows.filter((row) => row.added).length, 2);
  assert.equal(result.rows.filter((row) => row.removed.length).length, 2);
});

test('large files preserve distant unchanged lines using anchors', () => {
  const values = Array.from({length: 900}, (_, i) => `unique-content-line-${i}`);
  const changed = values.slice();
  changed[12] = 'first replacement';
  changed[850] = 'second replacement';
  const result = SourceDiff.displayRows(values.join('\n'), changed.join('\n'));
  assert.equal(result.rows.filter((row) => row.added).length, 2);
  assert.equal(result.rows.filter((row) => row.removed.length).length, 2);
  assert.equal(result.rows.length, 900);
});

test('a new file has only additions, not a fabricated deleted empty line', () => {
  const {rows, removedTail} = SourceDiff.displayRows('', 'hello\nworld');
  assert.deepEqual(rows.map((row) => row.added), [true, true]);
  assert.deepEqual(rows[0].removed, []);
  assert.deepEqual(removedTail, []);
  assert.equal(SourceDiff.displayRows('', '').rows[0].added, false);
});

test('empty lines, trailing newlines and repeated lines are preserved', () => {
  const previous = 'a\n\na\n';
  const current = 'a\n\nchanged\n';
  const result = SourceDiff.displayRows(previous, current);
  assert.equal(result.rows.map((row) => row.text).join('\n'), current);
  assert.equal(result.rows.filter((row) => row.added).length, 1);
  assert.deepEqual(result.removedTail, []);
});

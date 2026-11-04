'use strict';

const SourceDiff = (() => {
  function lineChanges(previous, current) {
    if (previous === '' && current === '') return [{type: 'equal', text: ''}];
    const oldLines = previous === '' ? [] : previous.split('\n');
    const newLines = current.split('\n');
    const changes = [];

    function append(type, text) {
      changes.push({type, text});
    }

    function findAnchors(aStart, aEnd, bStart, bEnd) {
      const oldPositions = new Map();
      const newPositions = new Map();
      for (let i = aStart; i < aEnd; i++) {
        const key = oldLines[i];
        oldPositions.set(key, oldPositions.has(key) ? -1 : i);
      }
      for (let j = bStart; j < bEnd; j++) {
        const key = newLines[j];
        newPositions.set(key, newPositions.has(key) ? -1 : j);
      }
      const pairs = [];
      for (let i = aStart; i < aEnd; i++) {
        const key = oldLines[i];
        if (oldPositions.get(key) === i && newPositions.has(key) && newPositions.get(key) >= 0) pairs.push([i, newPositions.get(key)]);
      }
      const tails = [];
      const predecessors = [];
      for (let i = 0; i < pairs.length; i++) {
        let left = 0, right = tails.length;
        while (left < right) {
          const middle = (left + right) >> 1;
          if (pairs[tails[middle]][1] < pairs[i][1]) left = middle + 1;
          else right = middle;
        }
        predecessors[i] = left ? tails[left - 1] : -1;
        tails[left] = i;
      }
      let last = tails.at(-1);
      const anchors = [];
      while (last !== undefined && last >= 0) {
        anchors.push(pairs[last]);
        last = predecessors[last];
      }
      return anchors.reverse();
    }

    function compare(aStart, aEnd, bStart, bEnd) {
      while (aStart < aEnd && bStart < bEnd && oldLines[aStart] === newLines[bStart]) {
        append('equal', oldLines[aStart]);
        aStart++;
        bStart++;
      }
      let suffix = 0;
      while (aStart + suffix < aEnd && bStart + suffix < bEnd && oldLines[aEnd - suffix - 1] === newLines[bEnd - suffix - 1]) suffix++;
      const oldEnd = aEnd - suffix;
      const newEnd = bEnd - suffix;
      const oldSize = oldEnd - aStart;
      const newSize = newEnd - bStart;
      if (!oldSize || !newSize) {
        for (let i = aStart; i < oldEnd; i++) append('removed', oldLines[i]);
        for (let j = bStart; j < newEnd; j++) append('added', newLines[j]);
      } else if (oldSize * newSize <= 350000) {
        const stride = newSize + 1;
        const lengths = new Uint32Array((oldSize + 1) * stride);
        for (let i = oldSize - 1; i >= 0; i--) {
          for (let j = newSize - 1; j >= 0; j--) {
            const offset = i * stride + j;
            lengths[offset] = oldLines[aStart + i] === newLines[bStart + j] ? lengths[offset + stride + 1] + 1 : Math.max(lengths[offset + stride], lengths[offset + 1]);
          }
        }
        let i = 0, j = 0;
        while (i < oldSize || j < newSize) {
          if (i < oldSize && j < newSize && oldLines[aStart + i] === newLines[bStart + j]) {
            append('equal', oldLines[aStart + i]); i++; j++;
          } else if (i < oldSize && (j === newSize || lengths[(i + 1) * stride + j] >= lengths[i * stride + j + 1])) {
            append('removed', oldLines[aStart + i++]);
          } else {
            append('added', newLines[bStart + j++]);
          }
        }
      } else {
        const anchors = findAnchors(aStart, oldEnd, bStart, newEnd);
        if (anchors.length) {
          let oldPosition = aStart, newPosition = bStart;
          for (const [i, j] of anchors) {
            compare(oldPosition, i, newPosition, j);
            append('equal', oldLines[i]);
            oldPosition = i + 1;
            newPosition = j + 1;
          }
          compare(oldPosition, oldEnd, newPosition, newEnd);
        } else {
          for (let i = aStart; i < oldEnd; i++) append('removed', oldLines[i]);
          for (let j = bStart; j < newEnd; j++) append('added', newLines[j]);
        }
      }
      for (let k = suffix; k > 0; k--) append('equal', oldLines[aEnd - k]);
    }

    compare(0, oldLines.length, 0, newLines.length);
    return changes;
  }

  function displayRows(previous, current) {
    const rows = [];
    let removed = [];
    let lineNumber = 0;
    for (const item of lineChanges(previous, current)) {
      if (item.type === 'removed') {
        removed.push(item.text);
      } else {
        rows.push({text: item.text, line: ++lineNumber, added: item.type === 'added', removed});
        removed = [];
      }
    }
    return {rows, removedTail: removed};
  }

  function editorValue(root) {
    return [...root.childNodes].map((node) => {
      if (node.nodeType === 3) return node.textContent;
      if (node.nodeName === 'BR') return '';
      return node.textContent;
    }).join('\n');
  }

  function captureCaret(root) {
    const selection = root.ownerDocument.getSelection();
    if (!selection || !selection.anchorNode || !root.contains(selection.anchorNode)) return null;
    function point(node, offset) {
      if (node === root) {
        return [...root.childNodes].slice(0, offset).reduce((total, child) => total + child.textContent.length + 1, 0) - (offset > 0 ? 1 : 0);
      }
      let row = node.nodeType === 3 ? node.parentNode : node;
      while (row && row.parentNode !== root) row = row.parentNode;
      if (!row) return 0;
      const previous = [...root.childNodes].slice(0, [...root.childNodes].indexOf(row));
      const base = previous.reduce((total, child) => total + child.textContent.length + 1, 0);
      const range = root.ownerDocument.createRange();
      range.selectNodeContents(row);
      range.setEnd(node, offset);
      return base + range.toString().length;
    }
    return {anchor: point(selection.anchorNode, selection.anchorOffset), focus: point(selection.focusNode, selection.focusOffset)};
  }

  function restoreCaret(root, source, position) {
    if (position === null) return;
    const lines = source.split('\n');
    const rows = [...root.children];
    function nodeAt(offset) {
      let remaining = Math.min(offset, source.length);
      for (let i = 0; i < lines.length; i++) {
        if (remaining <= lines[i].length || i === lines.length - 1) {
          const row = rows[i];
          if (row.firstChild && row.firstChild.nodeType === 3) return [row.firstChild, Math.min(remaining, row.firstChild.length)];
          return [row, 0];
        }
        remaining -= lines[i].length + 1;
      }
      return [rows.at(-1), 0];
    }
    const selection = root.ownerDocument.getSelection();
    const [anchorNode, anchorOffset] = nodeAt(position.anchor);
    const [focusNode, focusOffset] = nodeAt(position.focus);
    selection.setBaseAndExtent(anchorNode, anchorOffset, focusNode, focusOffset);
  }

  function render(root, previous, current, slideRange = null, scrollToSlide = false) {
    const focused = root.ownerDocument.activeElement === root;
    const caret = focused ? captureCaret(root) : null;
    const scrollTop = root.scrollTop;
    const scrollLeft = root.scrollLeft;
    const {rows, removedTail} = displayRows(previous, current);
    const documentFragment = root.ownerDocument.createDocumentFragment();
    for (const entry of rows) {
      const element = root.ownerDocument.createElement('div');
      const selected = slideRange && entry.line - 1 >= slideRange.start && entry.line - 1 < slideRange.end && slideRange.start >= 0;
      element.className = 'source-code-line' + (entry.added ? ' diff-added' : '') + (selected ? ' selected-slide-line' : '');
      element.dataset.line = String(entry.line);
      element.style.setProperty('--removed-count', entry.removed.length);
      if (entry.removed.length) element.dataset.removed = entry.removed.map((line) => '− ' + line).join('\n');
      element.textContent = entry.text;
      documentFragment.append(element);
    }
    root.replaceChildren(documentFragment);
    if (removedTail.length) root.dataset.removedTail = removedTail.map((line) => '− ' + line).join('\n');
    else delete root.dataset.removedTail;
    if (scrollToSlide && slideRange && slideRange.start >= 0) {
      const target = root.children[slideRange.start];
      root.scrollTop = target ? Math.max(0, target.offsetTop - root.offsetTop - 40) : scrollTop;
    } else {
      root.scrollTop = scrollTop;
    }
    root.scrollLeft = scrollLeft;
    if (focused) restoreCaret(root, current, caret);
  }

  function replaceSelection(root, source, replacement) {
    const selected = captureCaret(root);
    if (selected === null) return null;
    const start = Math.min(selected.anchor, selected.focus);
    const end = Math.max(selected.anchor, selected.focus);
    return {source: source.slice(0, start) + replacement + source.slice(end), caret: start + replacement.length};
  }

  return {lineChanges, displayRows, editorValue, render, captureCaret, restoreCaret, replaceSelection};
})();

if (typeof module !== 'undefined' && module.exports) module.exports = SourceDiff;

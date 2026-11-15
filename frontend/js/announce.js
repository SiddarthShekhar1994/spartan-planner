/**
 * Status messages for screen readers, through the one polite live region (#announcer).
 *
 * The region is cleared first and filled a moment later, so the same message twice in
 * a row is still read. Messages sent within that moment are read together instead of
 * the last one replacing the rest.
 */

const SETTLE_MS = 150;

let pending = [];
let timer = 0;

export function announce(text) {
  const message = typeof text === 'string' ? text.trim() : '';
  const region = document.getElementById('announcer');
  if (!message || !region) return;

  const sentence = /[.!?…]$/.test(message) ? message : `${message}.`;
  if (pending[pending.length - 1] !== sentence) pending.push(sentence);
  if (timer) return;

  region.textContent = '';
  timer = window.setTimeout(() => {
    region.textContent = pending.join(' ');
    pending = [];
    timer = 0;
  }, SETTLE_MS);
}

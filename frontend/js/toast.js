/**
 * Toasts, through the one polite live region (#toast). Anything that changes the plan
 * (removing a file, adding or changing a date, "Not sure yet") shows one with Undo.
 *
 * A toast with Undo stays 7 seconds, a plain one 3.4. It never disappears while the
 * pointer is over it or the keyboard is on its Undo button.
 */
import { el } from './icons.js';

const PLAIN_MS = 3400;
const UNDO_MS = 7000;
const HOLD_MS = 2000;

let timer = 0;
let pendingUndo = null;

function region() {
  return document.getElementById('toast');
}

/**
 * Show a message. Pass `onUndo` (it may return a promise) to add an Undo button.
 * A new toast replaces the one on screen.
 */
export function toast(message, onUndo = null) {
  const box = region();
  if (!box) return;
  window.clearTimeout(timer);
  pendingUndo = typeof onUndo === 'function' ? onUndo : null;
  box.replaceChildren(el('span', { class: 'toast-text' }, message));
  if (pendingUndo) box.append(el('button', { type: 'button', class: 'toast-undo', onclick: runUndo }, 'Undo'));
  timer = window.setTimeout(expire, pendingUndo ? UNDO_MS : PLAIN_MS);
}

/** Take the toast away now, for example when the screen changes. */
export function clearToast() {
  window.clearTimeout(timer);
  pendingUndo = null;
  region()?.replaceChildren();
}

function expire() {
  const box = region();
  if (!box) return;
  if (box.matches(':hover') || box.contains(document.activeElement)) {
    timer = window.setTimeout(expire, HOLD_MS);
    return;
  }
  clearToast();
}

async function runUndo() {
  const undo = pendingUndo;
  clearToast();
  if (!undo) return;
  try {
    await undo();
    toast('Undone.');
  } catch (error) {
    console.error(error);
    toast("I couldn't undo that. Try again.");
  }
}

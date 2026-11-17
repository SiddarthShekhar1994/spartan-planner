/**
 * Upload screen: the drop box under its "New class" tab, a paste box, one row per file,
 * and the "Found N dates in N classes." panel once every file is read.
 * Uploads run one at a time. The queue lives in this module rather than in the DOM, so
 * it keeps going if the student opens their dates and then comes back here.
 */
import { ApiError, listSyllabi, messageFor, renameSyllabus, uploadSyllabusFile, uploadSyllabusText } from '../api.js';
import { announce } from '../announce.js';
import { classColorMap } from '../class-colors.js';
import { formatCount, formatRetryAfter, plural } from '../format.js';
import { el, icon } from '../icons.js';
import { toast } from '../toast.js';
import { foundText, ROW_COPY, rowChildren, rowName } from './upload-rows.js';

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MIN_TEXT_CHARS = 50; // non-space characters, the same minimum the server uses
const MAX_TEXT_CHARS = 150000;
const ACCEPT = '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const SLOW_AFTER_MS = 15000;
const NO_RETRY_STATUSES = new Set([413, 415, 429]);
// Sending the same file or text again can only get the same answer for these.
const NO_RETRY_CODES = new Set(['text_too_short', 'no_text_found', 'unreadable_file']);
// What a finished row shows from its syllabus. If none of these change, the row isn't redrawn.
const ROW_FIELDS = ['class_name', 'item_count', 'needs_date_count'];

const COPY = {
  lead: "I'll pull out every deadline. You won't type a single date.",
  dropIdle: 'Drop PDF or Word files here',
  dropActive: 'Let go to upload',
  dropHint: 'Up to 10 MB each.',
  deleteNote: "I delete each file once I've read it.",
  pasteHint: `Paste the whole thing, or just the schedule and grading parts. Up to ${formatCount(MAX_TEXT_CHARS)} characters.`,
  wrongType: 'I can read PDF and Word (.docx) files.',
  tooBig: 'That file is over 10 MB.',
  noText: 'Paste some text first.',
  tooShort: "That's too short to be a syllabus. Paste the whole thing?",
  tooLong: `That's more than ${formatCount(MAX_TEXT_CHARS)} characters. Paste just the schedule and grading parts.`,
};

// Rows in display order: {key, kind: "file"|"text"|"saved", label, file, text,
// status: "queued"|"reading"|"done"|"error", syllabus, error: {status, code, message},
// editing, draft, renameError, saving, slow, slowTimer}.
const rows = [];
const classList = { status: 'idle', error: '' };
let nextKey = 1;
let uploading = false;
let loadToken = 0;
let view = null; // DOM references, only while this screen is on the page

export function render(container) {
  view = buildView();
  container.append(view.root);
  for (const row of rows) Object.assign(row, { editing: false, draft: null, renameError: '' });
  sortRows();
  view.list.append(...rows.map(buildRow));
  loadClasses(); // also draws the note, the list and the panel
  return () => {
    view = null;
  };
}

/* ---------- Layout ---------- */

function buildView() {
  const v = { items: new Map(), noteKey: '', readyKey: '' };
  v.fileInput = el('input', { type: 'file', class: 'visually-hidden', tabindex: '-1', 'aria-hidden': 'true', multiple: true, accept: ACCEPT });
  v.fileInput.addEventListener('change', () => {
    addFiles(v.fileInput.files);
    v.fileInput.value = ''; // so the same file can be picked again
  });
  v.chooseButton = el('button', { type: 'button', class: 'btn btn-primary', 'aria-describedby': 'drop-hint', onclick: () => v.fileInput.click() }, 'Choose files');
  v.dropTitle = el('p', { class: 'drop-title' }, COPY.dropIdle);
  v.zone = el('div', { class: 'drop' },
    el('div', { class: 'drop-text' }, v.dropTitle, el('p', { class: 'drop-hint', id: 'drop-hint' }, COPY.dropHint)),
    v.chooseButton, v.fileInput);
  bindDropZone(v);

  v.textarea = el('textarea', { id: 'paste-text', name: 'text', rows: '8', spellcheck: 'false', 'aria-describedby': 'paste-hint' });
  v.textarea.addEventListener('input', () => setPasteError(v, ''));
  v.pasteError = el('p', { class: 'field-err', id: 'paste-error', hidden: true });
  const onPaste = (event) => {
    event.preventDefault();
    submitPaste(v);
  };
  const pasteForm = el('form', { class: 'paste-form', novalidate: true, onsubmit: onPaste },
    el('label', { class: 'field-label', for: 'paste-text' }, 'Syllabus text'),
    el('p', { class: 'field-hint', id: 'paste-hint' }, COPY.pasteHint),
    v.textarea, v.pasteError,
    el('button', { type: 'submit', class: 'btn btn-secondary btn-sm' }, 'Read it'));

  v.heading = el('h1', { tabindex: '-1' }, 'Feed me your syllabi.');
  v.note = el('div', { class: 'classes-note' });
  v.list = el('ul', { class: 'files', 'aria-label': 'Your classes' });
  v.ready = el('div', { class: 'ready', hidden: true });
  v.root = el('div', { class: 'screen col' },
    v.heading, el('p', { class: 'lead' }, COPY.lead),
    el('section', { class: 'add', 'aria-label': 'Add a syllabus' },
      el('div', { class: 'tab tab-new' }, 'New class'), v.zone,
      el('p', { class: 'note' }, COPY.deleteNote),
      el('details', { class: 'paste' }, el('summary', {}, 'Paste text instead'), pasteForm)),
    v.note, v.list, v.ready);
  return v;
}

function bindDropZone(v) {
  let depth = 0; // dragenter and dragleave also fire for child elements, so count them
  const setDragging = (on) => {
    v.zone.classList.toggle('is-dragging', on);
    v.dropTitle.textContent = on ? COPY.dropActive : COPY.dropIdle;
  };
  const handlers = {
    dragenter: (event) => { event.preventDefault(); depth += 1; setDragging(true); },
    dragover: (event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; },
    dragleave: () => { depth = Math.max(0, depth - 1); if (depth === 0) setDragging(false); },
    drop: (event) => { event.preventDefault(); depth = 0; setDragging(false); addFiles(event.dataTransfer.files); },
  };
  for (const [type, handler] of Object.entries(handlers)) {
    v.zone.addEventListener(type, (event) => {
      if (Array.from(event.dataTransfer?.types ?? []).includes('Files')) handler(event);
    });
  }
}

/* ---------- Adding syllabi ---------- */

function newRow(fields) {
  return { key: `row-${nextKey++}`, status: 'queued', file: null, text: null, syllabus: null, error: null,
    editing: false, draft: null, renameError: '', saving: false, slow: false, slowTimer: 0, ...fields };
}

function addRow(fields) {
  const row = newRow(fields);
  rows.push(row);
  if (view) view.list.append(buildRow(row));
  syncChrome();
  return row;
}

function addFiles(fileList) {
  const added = Array.from(fileList ?? [], (file) => {
    const problem = checkFile(file);
    return addRow({ kind: 'file', file, label: file.name || 'Untitled file', ...(problem && { status: 'error', error: problem }) });
  });
  for (const row of added) if (row.status === 'error') say(statusMessage(row));
  startQueue(added.filter((row) => row.status === 'queued'));
}

/** The server checks again; this only saves a pointless upload. */
function checkFile(file) {
  const name = (file.name || '').toLowerCase();
  if (!name.endsWith('.pdf') && !name.endsWith('.docx')) return { status: 415, message: COPY.wrongType };
  if (file.size > MAX_FILE_BYTES) return { status: 413, message: COPY.tooBig };
  return null;
}

function submitPaste(v) {
  const text = v.textarea.value;
  const problem = checkPaste(text.trim());
  setPasteError(v, problem);
  if (problem) {
    v.textarea.focus();
    return;
  }
  v.textarea.value = '';
  startQueue([addRow({ kind: 'text', text, label: 'Pasted text' })]);
}

/** Mirrors the server's checks, in its order, so the error shows next to the box and the text stays in it. */
function checkPaste(trimmed) {
  if (!trimmed) return COPY.noText;
  if (trimmed.replace(/\s/g, '').length < MIN_TEXT_CHARS) return COPY.tooShort;
  if (trimmed.length > MAX_TEXT_CHARS) return COPY.tooLong;
  return '';
}

function setPasteError(v, message) {
  if (!message && v.pasteError.hidden) return;
  v.pasteError.replaceChildren(...(message ? [icon('alert'), el('span', {}, message)] : []));
  v.pasteError.hidden = !message;
  v.textarea.setAttribute('aria-describedby', message ? 'paste-hint paste-error' : 'paste-hint');
  if (message) v.textarea.setAttribute('aria-invalid', 'true');
  else v.textarea.removeAttribute('aria-invalid');
}

/* ---------- The queue: one upload at a time ---------- */

function startQueue(queued) {
  if (queued.length === 0) return;
  pump();
  const waiting = queued.filter((row) => row.status === 'queued');
  if (waiting.length === 1) say(statusMessage(waiting[0]));
  else if (waiting.length > 1) say(`${formatCount(waiting.length)} syllabi waiting in line.`);
}

async function pump() {
  if (uploading) return;
  const row = rows.find((candidate) => candidate.status === 'queued');
  if (!row) return;
  uploading = true;
  setStatus(row, 'reading');
  // Reading takes a while. After a bit, say so in words instead of adding more motion.
  row.slowTimer = window.setTimeout(() => {
    row.slow = true;
    view?.items.get(row.key)?.querySelector('.reading-note')?.removeAttribute('hidden');
  }, SLOW_AFTER_MS);
  try {
    const result = row.kind === 'text' ? await uploadSyllabusText(row.text) : await uploadSyllabusFile(row.file);
    Object.assign(row, { syllabus: result.syllabus, file: null, text: null, error: null });
    finishReading(row, 'done');
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 0;
    const code = error instanceof ApiError ? error.code : '';
    const wait = status === 429 && error.retryAfterSeconds ? ` Try again ${formatRetryAfter(error.retryAfterSeconds)}.` : '';
    row.error = { status, code, message: `${messageFor(error)}${wait}` };
    finishReading(row, 'error');
  } finally {
    uploading = false;
  }
  pump();
}

function finishReading(row, status) {
  window.clearTimeout(row.slowTimer);
  Object.assign(row, { slow: false, slowTimer: 0 });
  setStatus(row, status);
}

function setStatus(row, status) {
  row.status = status;
  renderRow(row);
  if (status === 'done') refreshColors();
  syncChrome();
  say(statusMessage(row));
}

function statusMessage(row) {
  if (row.status === 'queued') return `${row.label}: ${ROW_COPY.queued}`;
  if (row.status === 'reading') return `Reading ${row.label}`;
  if (row.status === 'error') return `${row.label}: ${row.error.message}`;
  return `${row.syllabus.class_name}: ${foundText(row.syllabus)}`;
}

function say(message) {
  if (view) announce(message);
}

/* ---------- Classes already saved on the server ---------- */

async function loadClasses() {
  const token = ++loadToken;
  Object.assign(classList, { status: 'loading', error: '' });
  syncChrome();
  try {
    const syllabi = await listSyllabi();
    if (token !== loadToken) return;
    mergeSaved(syllabi);
    Object.assign(classList, { status: 'ready', error: '' });
  } catch (error) {
    if (token !== loadToken) return;
    Object.assign(classList, { status: 'error', error: messageFor(error) });
    say(`I couldn't check for your classes. ${classList.error}`);
  }
  syncChrome();
}

function mergeSaved(syllabi) {
  const known = new Map(rows.filter((row) => row.syllabus).map((row) => [row.syllabus.id, row]));
  const fresh = [];
  for (const syllabus of [...syllabi].sort((a, b) => a.id - b.id)) {
    const existing = known.get(syllabus.id);
    if (!existing) fresh.push(newRow({ kind: 'saved', label: syllabus.class_name, status: 'done', syllabus }));
    else if (!existing.editing && !existing.saving) {
      const changed = ROW_FIELDS.some((field) => existing.syllabus[field] !== syllabus[field]);
      existing.syllabus = syllabus;
      if (changed) renderRow(existing);
    }
  }
  rows.unshift(...fresh); // saved classes go above anything added during this visit
  if (view) {
    const first = view.list.firstChild;
    for (const row of fresh) view.list.insertBefore(buildRow(row), first);
  }
  refreshColors();
}

/** Done rows by id (so colors stay put), then everything still in progress, in the order added. */
function sortRows() {
  const done = rows.filter((row) => row.status === 'done').sort((a, b) => a.syllabus.id - b.syllabus.id);
  rows.splice(0, rows.length, ...done, ...rows.filter((row) => row.status !== 'done'));
}

/* ---------- Rows ---------- */

function buildRow(row) {
  const li = el('li', { tabindex: '-1' });
  view.items.set(row.key, li);
  fillRow(li, row);
  return li;
}

/** Redraw a row. If focus was in it, it goes back to the same control, or to the row itself. */
function renderRow(row) {
  const li = view?.items.get(row.key);
  if (!li) return;
  const hadFocus = li.contains(document.activeElement);
  const action = hadFocus ? document.activeElement.getAttribute('data-action') : null;
  fillRow(li, row);
  if (!hadFocus || li.contains(document.activeElement)) return;
  const control = action ? li.querySelector(`[data-action="${action}"]`) : null;
  (control ?? li).focus();
}

function rowHasFocus(row) {
  return Boolean(view?.items.get(row.key)?.contains(document.activeElement));
}

function fillRow(li, row) {
  li.className = row.status === 'error' ? 'file is-error' : 'file';
  li.dataset.status = row.status;
  const color = row.status === 'done' ? classColorMap(doneSyllabi()).get(row.syllabus.id) : undefined;
  li.replaceChildren(...rowChildren(row, color, {
    rename: () => startRename(row),
    cancelRename: () => stopRename(row),
    saveRename: (input, button) => saveRename(row, input, button),
    retry: () => retry(row),
    remove: () => remove(row),
    canRetry: row.status === 'error' && !NO_RETRY_STATUSES.has(row.error.status) && !NO_RETRY_CODES.has(row.error.code),
  }));
}

/** Colors follow the order classes were added, so a new class can change which color a row gets. */
function refreshColors() {
  if (!view) return;
  const colors = classColorMap(doneSyllabi());
  for (const row of rows) {
    if (row.status !== 'done') continue;
    const badge = view.items.get(row.key)?.querySelector('.badge');
    const color = colors.get(row.syllabus.id);
    if (badge && color) badge.style.setProperty('--class-color', color);
  }
}

function doneSyllabi() {
  return rows.filter((row) => row.status === 'done').map((row) => row.syllabus);
}

function retry(row) {
  Object.assign(row, { status: 'queued', error: null });
  renderRow(row);
  syncChrome();
  view?.items.get(row.key)?.focus();
  startQueue([row]);
}

/** Take a row that couldn't be read off the list. The toast's Undo puts it back where it was. */
function remove(row) {
  const index = rows.indexOf(row);
  if (index === -1) return;
  rows.splice(index, 1);
  const li = view?.items.get(row.key);
  const next = li?.nextElementSibling ?? li?.previousElementSibling ?? view?.chooseButton;
  li?.remove();
  view?.items.delete(row.key);
  syncChrome();
  next?.focus();
  toast(`Removed ${row.label}.`, () => restore(row, index));
}

function restore(row, index) {
  if (rows.includes(row)) return;
  rows.splice(Math.min(index, rows.length), 0, row);
  if (view) {
    view.items.clear();
    view.list.replaceChildren(...rows.map(buildRow));
    view.items.get(row.key)?.focus();
  }
  syncChrome();
}

/* ---------- Rename ---------- */

function startRename(row) {
  Object.assign(row, { editing: true, draft: null, renameError: '' });
  renderRow(row);
  const input = view?.items.get(row.key)?.querySelector('input');
  input?.focus();
  input?.select();
}

/** Back to the class name. focus: false leaves focus where it is, for when the student has moved on. */
function stopRename(row, message = '', { focus = true } = {}) {
  Object.assign(row, { editing: false, draft: null, renameError: '' });
  renderRow(row);
  if (focus) view?.items.get(row.key)?.querySelector('[data-action="rename"]')?.focus();
  if (message) say(message);
}

async function saveRename(row, input, save) {
  if (row.saving) return;
  const name = input.value.replace(/\s+/g, ' ').trim();
  if (name === row.syllabus.class_name) {
    stopRename(row);
    return;
  }
  row.saving = true;
  save.textContent = 'Saving…';
  try {
    row.syllabus = await renameSyllabus(row.syllabus.id, name);
    const hadFocus = rowHasFocus(row); // they may have tabbed on while it saved
    row.saving = false;
    const message = `Renamed to ${row.syllabus.class_name}.`;
    if (row.editing) stopRename(row, message, { focus: hadFocus });
    else {
      renderRow(row); // they cancelled while it saved: show the new name (renderRow keeps focus where it is)
      say(message);
    }
  } catch (error) {
    const hadFocus = rowHasFocus(row);
    Object.assign(row, { saving: false, draft: input.value, renameError: messageFor(error) });
    if (!row.editing) return;
    renderRow(row);
    if (hadFocus) view?.items.get(row.key)?.querySelector('input')?.focus();
    else say(`I couldn't rename ${rowName(row)}. ${row.renameError}`); // the error shows in the row too
  }
}

/* ---------- Everything around the list ---------- */

function syncChrome() {
  if (!view) return;
  const hasRows = rows.length > 0;
  const done = doneSyllabi();
  const busy = rows.some((row) => row.status === 'queued' || row.status === 'reading');
  // Wait for the whole queue, so the dates screen never shows half of what's coming.
  const ready = done.length > 0 && !busy;
  // One main action at a time: Choose files until every class is read, then Next.
  view.chooseButton.classList.toggle('btn-primary', !ready);
  view.chooseButton.classList.toggle('btn-secondary', ready);
  view.list.hidden = !hasRows;
  syncReady(ready, done);

  const noteKey = `${classList.status}|${classList.error}`;
  if (noteKey === view.noteKey) return; // don't rebuild a note that might hold focus
  view.noteKey = noteKey;
  view.note.replaceChildren(...noteContent());
}

/** "Found 11 dates in 3 classes." The panel is rebuilt only when its numbers change. */
function syncReady(ready, done) {
  const total = done.reduce((sum, syllabus) => sum + syllabus.item_count, 0);
  const missing = done.reduce((sum, syllabus) => sum + syllabus.needs_date_count, 0);
  const key = ready ? `${total}|${missing}|${done.length}` : '';
  if (key === view.readyKey) return;
  view.readyKey = key;
  view.ready.hidden = !ready;
  if (!ready) {
    view.ready.replaceChildren();
    return;
  }
  if (total === 0) {
    view.ready.replaceChildren(
      el('p', { class: 'big-count' }, 'No dates found yet.'),
      el('p', { class: 'muted' }, "If your syllabus is a scan, try pasting its text."));
    return;
  }
  const classes = `${formatCount(done.length)} ${plural(done.length, 'class', 'classes')}`;
  const dates = `${formatCount(total)} ${plural(total, 'date', 'dates')}`;
  let detail = 'Every one has a date.';
  if (missing === 1) detail = "1 doesn't have a date yet. I'll ask you about it.";
  else if (missing > 1) detail = `${formatCount(missing)} don't have a date yet. I'll ask you about those.`;
  view.ready.replaceChildren(
    el('p', { class: 'big-count' }, `Found ${dates} in ${classes}.`),
    el('p', { class: 'muted' }, detail),
    el('div', { class: 'actions' }, el('a', { class: 'btn btn-primary', href: '#/hours' }, 'Next')));
}

function noteContent() {
  if (classList.status === 'loading') return [el('p', { class: 'note' }, 'Checking for your classes…')];
  if (classList.status === 'error') {
    const retryLoad = () => {
      view?.heading.focus(); // the Try again button is about to go away
      loadClasses();
    };
    return [el('div', { class: 'notice' }, icon('alert'),
      el('div', { class: 'notice-body' },
        el('p', { class: 'notice-title' }, "I couldn't check for your classes."),
        el('p', {}, classList.error),
        el('button', { type: 'button', class: 'btn btn-secondary btn-sm', onclick: retryLoad }, 'Try again')))];
  }
  return [];
}

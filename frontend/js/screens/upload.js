/**
 * Upload screen: a drop zone, a file picker, a paste box, and the "Your classes" list.
 * Uploads run one at a time. The queue lives in this module rather than in the DOM, so
 * it keeps going if the student opens their dates and then comes back here.
 */
import { ApiError, listSyllabi, messageFor, renameSyllabus, uploadSyllabusFile, uploadSyllabusText } from '../api.js';
import { announce } from '../announce.js';
import { classColorMap } from '../class-colors.js';
import { formatCount, formatRetryAfter, plural } from '../format.js';
import { dotted, el, icon } from '../icons.js';

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MIN_TEXT_CHARS = 50; // non-space characters, the same minimum the server uses
const MAX_TEXT_CHARS = 150000;
const MAX_CLASS_NAME_CHARS = 120;
const ACCEPT = '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const NO_RETRY_STATUSES = new Set([413, 415, 429]);
// Sending the same file or text again can only get the same answer for these.
const NO_RETRY_CODES = new Set(['text_too_short', 'no_text_found', 'unreadable_file']);
// What a finished row shows from its syllabus. If none of these change, the row isn't redrawn.
const ROW_FIELDS = ['class_name', 'item_count', 'needs_date_count', 'unverified_count'];

const COPY = {
  lead: "Drop in a PDF or Word file, up to 10 MB each. I'll find every deadline and show you the exact sentence I found it in.",
  dropIdle: 'Drag syllabus files here',
  dropActive: 'Let go to upload',
  pasteHint: `Paste the whole thing, or just the schedule and grading parts. Up to ${formatCount(MAX_TEXT_CHARS)} characters.`,
  queued: 'Waiting in line…',
  reading: 'Reading it now…',
  zeroItems: "No dates found in this one. If it's a scan, try pasting the text.",
  empty: 'Nothing here yet. Your classes show up here as I read them.',
  wrongType: 'I can read PDF and Word (.docx) files.',
  tooBig: 'That file is over 10 MB.',
  noText: 'Paste some text first.',
  tooShort: "That's too short to be a syllabus. Paste the whole thing?",
  tooLong: `That's more than ${formatCount(MAX_TEXT_CHARS)} characters. Paste just the schedule and grading parts.`,
};

// Rows in display order: {key, kind: "file"|"text"|"saved", label, file, text,
// status: "queued"|"reading"|"done"|"error", syllabus, error: {status, code, message},
// editing, draft, renameError, saving, justDone}.
const rows = [];
const classList = { status: 'idle', error: '' };
let nextKey = 1;
let uploading = false;
let loadToken = 0;
let view = null; // DOM references, only while this screen is on the page

export function render(container) {
  view = buildView();
  container.append(view.root);
  for (const row of rows) Object.assign(row, { editing: false, draft: null, renameError: '', justDone: false });
  sortRows();
  view.list.append(...rows.map(buildRow));
  loadClasses(); // also draws the note, the list and the buttons
  return () => {
    view = null;
  };
}

/* ---------- Layout ---------- */

function buildView() {
  const v = { items: new Map(), noteKey: '' };
  v.fileInput = el('input', { type: 'file', class: 'visually-hidden', tabindex: '-1', 'aria-hidden': 'true', multiple: true, accept: ACCEPT });
  v.fileInput.addEventListener('change', () => {
    addFiles(v.fileInput.files);
    v.fileInput.value = ''; // so the same file can be picked again
  });
  v.chooseButton = el('button', { type: 'button', class: 'button button-primary', 'aria-describedby': 'drop-hint', onclick: () => v.fileInput.click() }, 'Choose files');
  v.dropTitle = el('p', { class: 'drop-title' }, COPY.dropIdle);
  v.zone = el('div', { class: 'drop-zone' },
    el('span', { class: 'drop-icon' }, icon('upload')), v.dropTitle, el('p', { class: 'drop-or' }, 'or'),
    v.chooseButton, v.fileInput, el('p', { class: 'drop-hint', id: 'drop-hint' }, 'PDF or .docx, up to 10 MB'));
  bindDropZone(v);

  v.textarea = el('textarea', { id: 'paste-text', name: 'text', rows: '8', spellcheck: 'false', 'aria-describedby': 'paste-hint' });
  v.textarea.addEventListener('input', () => setPasteError(v, ''));
  v.pasteError = el('p', { class: 'field-error', id: 'paste-error', hidden: true });
  const onPaste = (event) => {
    event.preventDefault();
    submitPaste(v);
  };
  const pasteForm = el('form', { class: 'paste-form', novalidate: true, onsubmit: onPaste },
    el('label', { class: 'field-label', for: 'paste-text' }, 'Syllabus text'),
    el('p', { class: 'field-hint', id: 'paste-hint' }, COPY.pasteHint),
    v.textarea, v.pasteError,
    el('button', { type: 'submit', class: 'button button-secondary' }, 'Read it'));

  v.heading = el('h2', { id: 'classes-heading', tabindex: '-1' }, 'Your classes');
  v.note = el('div', { class: 'classes-note' });
  v.list = el('ul', { class: 'class-list', role: 'list' });
  v.seeDates = el('a', { class: 'button button-primary see-dates', href: '#/dates', hidden: true }, 'See my dates', icon('arrow-right'));
  v.root = el('div', { class: 'screen upload-screen' },
    el('header', { class: 'screen-header' }, el('h1', { tabindex: '-1' }, 'Feed me your syllabi.'), el('p', { class: 'lead' }, COPY.lead)),
    el('div', { class: 'upload-layout' },
      el('section', { class: 'upload-add', 'aria-label': 'Add a syllabus' },
        v.zone, el('details', { class: 'paste' }, el('summary', {}, icon('chevron'), 'Paste text instead'), pasteForm)),
      el('section', { class: 'classes', 'aria-labelledby': 'classes-heading' }, v.heading, v.note, v.list, v.seeDates)));
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
    editing: false, draft: null, renameError: '', saving: false, justDone: false, ...fields };
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
  try {
    const result = row.kind === 'text' ? await uploadSyllabusText(row.text) : await uploadSyllabusFile(row.file);
    Object.assign(row, { syllabus: result.syllabus, file: null, text: null, error: null });
    setStatus(row, 'done');
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 0;
    const code = error instanceof ApiError ? error.code : '';
    const wait = status === 429 && error.retryAfterSeconds ? ` Try again ${formatRetryAfter(error.retryAfterSeconds)}.` : '';
    row.error = { status, code, message: `${messageFor(error)}${wait}` };
    setStatus(row, 'error');
  } finally {
    uploading = false;
  }
  pump();
}

function setStatus(row, status) {
  row.status = status;
  row.justDone = status === 'done';
  renderRow(row);
  if (status === 'done') refreshColors();
  syncChrome();
  say(statusMessage(row));
}

function statusMessage(row) {
  if (row.status === 'queued') return `${row.label}: ${COPY.queued}`;
  if (row.status === 'reading') return `${row.label}: ${COPY.reading}`;
  if (row.status === 'error') return `${row.label}: ${row.error.message}`;
  const { class_name: name, item_count: count } = row.syllabus;
  return count ? `${name}: ${summaryParts(row.syllabus).join(', ')}` : `${name}: ${COPY.zeroItems}`;
}

/** "14 dates found", then only the parts that aren't zero. */
function summaryParts({ item_count: found, needs_date_count: needDate, unverified_count: unverified }) {
  const parts = [`${formatCount(found)} ${plural(found, 'date', 'dates')} found`];
  if (needDate > 0) parts.push(`${formatCount(needDate)} ${plural(needDate, 'needs a date', 'need a date')}`);
  if (unverified > 0) parts.push(`${formatCount(unverified)} ${plural(unverified, 'quote', 'quotes')} to double-check`);
  return parts;
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
  const li = el('li', { class: 'class-row', tabindex: '-1' });
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
  li.dataset.status = row.status;
  const body = el('div', { class: 'class-row-body' },
    row.editing ? renameForm(row) : el('p', { class: 'class-row-name' }, rowName(row)), statusLine(row));
  const actions = rowActions(row);
  li.replaceChildren(el('span', { class: 'class-dot', 'aria-hidden': 'true' }), body, ...(actions.childElementCount ? [actions] : []));
  paintDot(li, row, classColorMap(doneSyllabi()));
  row.justDone = false;
}

function rowName(row) {
  return row.status === 'done' ? row.syllabus.class_name : row.label;
}

function statusLine(row) {
  const line = el('p', { class: 'class-row-status' });
  if (row.status === 'queued') line.append(icon('clock'), el('span', {}, COPY.queued));
  else if (row.status === 'reading') line.append(icon('spinner', 'icon-spin'), el('span', {}, COPY.reading));
  else if (row.status === 'error') line.append(icon('alert'), el('span', {}, row.error.message));
  else if (!row.syllabus.item_count) line.append(icon('info'), el('span', {}, COPY.zeroItems));
  else line.append(icon('check', row.justDone ? 'is-popping' : ''), el('span', {}, dotted(summaryParts(row.syllabus))));
  return line;
}

function rowActions(row) {
  const actions = el('div', { class: 'class-row-actions' });
  const name = rowName(row);
  if (row.status === 'done' && !row.editing) actions.append(rowButton('Rename', name, () => startRename(row), 'rename'));
  if (row.status === 'error') {
    const { status, code } = row.error;
    if (!NO_RETRY_STATUSES.has(status) && !NO_RETRY_CODES.has(code)) actions.append(rowButton('Try again', name, () => retry(row)));
    actions.append(rowButton('Dismiss', name, () => dismiss(row)));
  }
  return actions;
}

/** Visible text first, then the class for screen readers: "Rename CS 101". */
function rowButton(label, context, onclick, action = null) {
  return el('button', { type: 'button', class: 'button button-quiet', 'data-action': action, onclick },
    label, el('span', { class: 'visually-hidden' }, ` ${context}`));
}

function paintDot(li, row, colors) {
  const dot = li.querySelector('.class-dot');
  const color = row.status === 'done' ? colors.get(row.syllabus.id) : undefined;
  dot.classList.toggle('is-pending', !color);
  if (color) dot.style.setProperty('--class-color', color);
  else dot.style.removeProperty('--class-color');
}

function refreshColors() {
  if (!view) return;
  const colors = classColorMap(doneSyllabi());
  for (const row of rows) {
    const li = view.items.get(row.key);
    if (li) paintDot(li, row, colors);
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

function dismiss(row) {
  const index = rows.indexOf(row);
  if (index !== -1) rows.splice(index, 1);
  const li = view?.items.get(row.key);
  const next = li?.nextElementSibling ?? li?.previousElementSibling ?? view?.heading;
  li?.remove();
  view?.items.delete(row.key);
  syncChrome();
  next?.focus();
  say(`Removed ${row.label}.`);
}

/* ---------- Rename ---------- */

function renameForm(row) {
  const id = `rename-${row.key}`;
  const errorId = `${id}-error`;
  const input = el('input', {
    id, type: 'text', class: 'text-input', value: row.draft ?? row.syllabus.class_name,
    maxlength: String(MAX_CLASS_NAME_CHARS), autocomplete: 'off', spellcheck: 'false',
    'aria-invalid': row.renameError ? 'true' : null, 'aria-describedby': row.renameError ? errorId : null,
  });
  input.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    stopRename(row);
  });
  const save = el('button', { type: 'submit', class: 'button button-secondary' }, 'Save');
  const onSubmit = (event) => {
    event.preventDefault();
    saveRename(row, input, save);
  };
  return el('form', { class: 'rename-form', novalidate: true, onsubmit: onSubmit },
    el('label', { class: 'visually-hidden', for: id }, 'Class name'),
    el('div', { class: 'rename-controls' },
      input, save, el('button', { type: 'button', class: 'button button-quiet', onclick: () => stopRename(row) }, 'Cancel')),
    row.renameError ? el('p', { class: 'field-error', id: errorId }, icon('alert'), el('span', {}, row.renameError)) : null);
}

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
    else say(`I couldn't rename ${row.syllabus.class_name}. ${row.renameError}`); // the error shows in the row too
  }
}

/* ---------- Everything around the list ---------- */

function syncChrome() {
  if (!view) return;
  const hasRows = rows.length > 0;
  const hasDone = rows.some((row) => row.status === 'done');
  const busy = rows.some((row) => row.status === 'queued' || row.status === 'reading');
  // Wait for the whole queue, so the dates list never shows half of what's coming.
  const ready = hasDone && !busy;
  view.seeDates.hidden = !ready;
  // Lime marks the one main action: Choose files until every class is read, then See my dates.
  view.chooseButton.classList.toggle('button-primary', !ready);
  view.chooseButton.classList.toggle('button-secondary', ready);
  view.list.hidden = !hasRows;
  const noteKey = `${classList.status}|${hasRows}|${classList.error}`;
  if (noteKey === view.noteKey) return; // don't rebuild a note that might hold focus
  view.noteKey = noteKey;
  view.note.replaceChildren(...noteContent(hasRows));
}

function noteContent(hasRows) {
  if (classList.status === 'loading') {
    return [el('p', { class: 'loading-note' }, icon('spinner', 'icon-spin'), el('span', {}, 'Checking for your classes…'))];
  }
  if (classList.status === 'error') {
    const retryLoad = () => {
      view?.heading.focus(); // the Try again button is about to go away
      loadClasses();
    };
    return [el('div', { class: 'notice' }, icon('alert'),
      el('div', { class: 'notice-body' },
        el('p', { class: 'notice-title' }, "I couldn't check for your classes."),
        el('p', {}, classList.error),
        el('button', { type: 'button', class: 'button button-secondary', onclick: retryLoad }, 'Try again')))];
  }
  return hasRows ? [] : [el('p', { class: 'classes-empty' }, COPY.empty)];
}

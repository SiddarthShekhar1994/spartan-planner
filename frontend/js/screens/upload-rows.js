/**
 * What one row on the upload screen looks like in each state: up next, reading,
 * read (with the class color and Rename), or couldn't read (amber, with Remove).
 * These only build DOM. The queue and the saving live in upload.js.
 */
import { formatCount, plural } from '../format.js';
import { el, icon } from '../icons.js';

export const MAX_CLASS_NAME_CHARS = 120;

export const ROW_COPY = {
  queued: 'Up next',
  slow: 'Still reading. Long ones can take a minute.',
  zeroItems: "No dates found in this one. If it's a scan, try pasting the text.",
};

const PAGE_LINE_WIDTHS = [92, 70, 84, 60, 88, 74, 52];

/** The name a row goes by: the class name once it's read, the file name before that. */
export function rowName(row) {
  return row.status === 'done' ? row.syllabus.class_name : row.label;
}

/** "14 dates found", or the no-dates line. */
export function foundText(syllabus) {
  const count = syllabus.item_count;
  return count ? `${formatCount(count)} ${plural(count, 'date', 'dates')} found` : ROW_COPY.zeroItems;
}

/**
 * The children of one row's <li>.
 * @param row      see upload.js for the fields
 * @param color    the class color for a read row, or undefined
 * @param actions  {rename, cancelRename, saveRename(input, button), retry, remove, canRetry}
 */
export function rowChildren(row, color, actions) {
  if (row.status === 'reading') return [readingBlock(row)];
  if (row.status === 'error') return errorParts(row, actions);
  if (row.status === 'done') return doneParts(row, color, actions);
  return [
    el('span', { class: 'badge badge-wait', 'aria-hidden': 'true' }),
    who(row.label, el('span', { class: 'muted' }, ROW_COPY.queued)),
  ];
}

function who(name, detail) {
  return el('div', { class: 'file-who' }, el('span', { class: 'file-name' }, name), detail);
}

/** A little page with one slow highlighter pass, next to "Reading cs146.pdf…". */
function readingBlock(row) {
  const page = el('div', { class: 'page', 'aria-hidden': 'true' },
    PAGE_LINE_WIDTHS.map((width) => el('i', { style: { width: `${width}%` } })),
    el('span', { class: 'sweep' }));
  return el('div', { class: 'reading' }, page,
    el('div', { class: 'file-who' },
      el('p', { class: 'file-name' }, `Reading ${row.label}…`),
      el('p', { class: 'muted reading-note', hidden: !row.slow }, ROW_COPY.slow)));
}

function doneParts(row, color, actions) {
  const badge = el('span', { class: 'badge', 'aria-hidden': 'true', style: color ? { '--class-color': color } : {} }, icon('check'));
  if (row.editing) return [badge, renameForm(row, actions)];
  return [
    badge,
    who(row.syllabus.class_name, el('span', { class: 'muted' }, foundText(row.syllabus))),
    el('div', { class: 'file-actions' }, linkButton('Rename', row.syllabus.class_name, actions.rename, 'rename')),
  ];
}

function errorParts(row, actions) {
  return [
    el('span', { class: 'badge badge-bad', 'aria-hidden': 'true' }, icon('alert')),
    who(row.label, el('span', { class: 'file-why' }, row.error.message)),
    el('div', { class: 'file-actions' },
      actions.canRetry ? linkButton('Try again', row.label, actions.retry, 'retry') : null,
      linkButton('Remove', row.label, actions.remove, 'remove')),
  ];
}

/** Visible text first, then the name for screen readers: "Rename CS 101". */
function linkButton(label, context, onclick, action) {
  return el('button', { type: 'button', class: 'btn btn-link btn-sm', 'data-action': action, onclick },
    label, el('span', { class: 'visually-hidden' }, ` ${context}`));
}

function renameForm(row, actions) {
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
    actions.cancelRename();
  });
  const save = el('button', { type: 'submit', class: 'btn btn-primary btn-sm' }, 'Save');
  const onsubmit = (event) => {
    event.preventDefault();
    actions.saveRename(input, save);
  };
  return el('form', { class: 'file-who rename-form', novalidate: true, onsubmit },
    el('label', { class: 'visually-hidden', for: id }, 'Class name'),
    el('div', { class: 'rename-controls' },
      input, save, el('button', { type: 'button', class: 'btn btn-link btn-sm', onclick: actions.cancelRename }, 'Cancel')),
    row.renameError ? el('p', { class: 'field-err', id: errorId }, icon('alert'), el('span', {}, row.renameError)) : null);
}

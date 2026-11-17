/**
 * The pieces of the "Got N dates." screen: one date row (it opens to show the source
 * sentence and a way to change the date), one "needs a date" block for the amber box,
 * and one row for an item the student marked "Not sure yet".
 * These only build DOM. Loading and saving live in dates.js.
 *
 * ctx for every builder:
 *   {code, className, color, open, opening, editing, error, draft,
 *    on: {toggle, edit, cancel, save(value, button), skip(button), draft(value)}}
 */
import { formatDayParts, formatLongDate } from '../format.js';
import { splitAround } from '../highlight.js';
import { el, icon } from '../icons.js';

const COPY = {
  ask: "I didn't guess. When is it actually due?",
  unverified: "I couldn't find this exact sentence in your syllabus. Make sure the date is right.",
  worthALook: 'Worth a look',
  youSet: 'You set this',
};

/** The sentence in curly quotes, with the date words highlighted: lime for a date, amber when there is none. */
export function quoteNodes(item) {
  const { before, match, after } = splitAround(item.source_text, item.date_text);
  const mark = match ? el('mark', { class: item.due_date ? 'hl' : 'hl hl-amb' }, match) : null;
  return ['“', before, mark, after, '”'];
}

function chip(ctx) {
  return el('span', { class: ctx.color ? 'chip' : 'chip chip-plain', title: ctx.className, style: ctx.color ? { '--class-color': ctx.color } : {} }, ctx.code);
}

function unverifiedFlag(item) {
  return item.source_verified ? null : el('span', { class: 'flag' }, icon('alert'), COPY.worthALook);
}

/**
 * A date field with its buttons and its inline error. Enter in the field submits.
 * `skipLabel` adds a second, quieter button ("Not sure yet" or "Cancel").
 */
function dateForm(item, ctx, { value, saveLabel, skipLabel, onSkip }) {
  const inputId = `date-${item.id}`;
  const errorId = `date-err-${item.id}`;
  const error = el('p', { class: 'field-err', id: errorId, hidden: !ctx.error }, icon('alert'), el('span', {}, ctx.error ?? ''));
  const input = el('input', {
    id: inputId, class: 'date-in', type: 'date', value: ctx.draft ?? value ?? '', min: '2000-01-01', max: '2100-12-31',
    'aria-describedby': errorId, 'aria-invalid': ctx.error ? 'true' : null,
  });
  input.addEventListener('input', () => {
    ctx.on.draft(input.value);
    error.hidden = true;
    input.removeAttribute('aria-invalid');
  });
  const save = el('button', { type: 'submit', class: 'btn btn-primary btn-sm' }, saveLabel);
  const onsubmit = (event) => {
    event.preventDefault();
    ctx.on.save(input.value, save);
  };
  return el('form', { class: 'date-form', novalidate: true, onsubmit },
    el('div', { class: 'need-row' },
      el('label', { class: 'visually-hidden', for: inputId }, `Date for ${item.title}`),
      input, save,
      el('button', { type: 'button', class: 'btn btn-link btn-sm', onclick: (event) => onSkip(event.currentTarget) }, skipLabel)),
    error);
}

/** One dated row. Closed: day, title, class chip, flags. Open: the sentence and "Change the date". */
export function dateRow(item, ctx) {
  const parts = formatDayParts(item.due_date);
  const toggle = el('button', {
    type: 'button', class: 'drow-toggle', id: `row-${item.id}`,
    'aria-expanded': String(ctx.open), 'aria-controls': ctx.open ? `more-${item.id}` : null, onclick: ctx.on.toggle,
  },
  el('span', { class: 'dday', 'aria-hidden': 'true' }, el('small', {}, parts.weekday), el('b', {}, parts.day), el('small', {}, parts.month)),
  el('span', { class: 'dwhat' },
    el('span', { class: 'dwhat-title' }, item.title, el('span', { class: 'visually-hidden' }, `, ${formatLongDate(item.due_date)}`)),
    el('span', { class: 'dwhat-tags' }, chip(ctx), unverifiedFlag(item),
      item.status === 'edited' ? el('span', { class: 'flag flag-quiet' }, COPY.youSet) : null)),
  icon('chevron', 'chev'));

  const more = ctx.open ? el('div', { class: ctx.opening ? 'more is-opening' : 'more', id: `more-${item.id}` },
    el('p', { class: 'src-cap' }, item.status === 'edited' ? 'Your syllabus said' : 'From your syllabus'),
    el('p', { class: 'src' }, quoteNodes(item)),
    item.source_verified ? null : el('p', { class: 'warn' }, COPY.unverified),
    ctx.editing
      ? dateForm(item, ctx, { value: item.due_date, saveLabel: 'Save', skipLabel: 'Cancel', onSkip: ctx.on.cancel })
      : el('button', { type: 'button', class: 'btn btn-secondary btn-sm', id: `edit-${item.id}`, onclick: ctx.on.edit }, 'Change the date')) : null;

  return el('li', { class: ctx.open ? 'drow is-open' : 'drow' }, toggle, more);
}

/** One item in the amber box: the sentence, the question, a date field, Add and "Not sure yet". */
export function needBlock(item, ctx) {
  return el('div', { class: 'need' },
    el('p', { class: 'need-title' }, chip(ctx), el('b', {}, item.title)),
    el('p', { class: 'need-q' }, quoteNodes(item)),
    item.source_verified ? null : el('p', { class: 'need-q warn' }, COPY.unverified),
    el('p', { class: 'need-q muted' }, COPY.ask),
    dateForm(item, ctx, { saveLabel: 'Add', skipLabel: 'Not sure yet', onSkip: ctx.on.skip }));
}

/** An item waiting for a date after "Not sure yet". It opens to the sentence and a date field. */
export function waitingRow(item, ctx) {
  const toggle = el('button', {
    type: 'button', class: 'drow-toggle', id: `row-${item.id}`,
    'aria-expanded': String(ctx.open), 'aria-controls': ctx.open ? `more-${item.id}` : null, onclick: ctx.on.toggle,
  },
  el('span', { class: 'dday', 'aria-hidden': 'true' }, el('small', {}, 'No'), el('small', {}, 'date')),
  el('span', { class: 'dwhat' },
    el('span', { class: 'dwhat-title' }, item.title, el('span', { class: 'visually-hidden' }, ', no date yet')),
    el('span', { class: 'dwhat-tags' }, chip(ctx), unverifiedFlag(item))),
  icon('chevron', 'chev'));

  const more = ctx.open ? el('div', { class: ctx.opening ? 'more is-opening' : 'more', id: `more-${item.id}` },
    el('p', { class: 'src-cap' }, 'From your syllabus'),
    el('p', { class: 'src' }, quoteNodes(item)),
    item.source_verified ? null : el('p', { class: 'warn' }, COPY.unverified),
    dateForm(item, ctx, { saveLabel: 'Add', skipLabel: 'Cancel', onSkip: ctx.on.toggle })) : null;

  return el('li', { class: ctx.open ? 'drow is-open' : 'drow' }, toggle, more);
}

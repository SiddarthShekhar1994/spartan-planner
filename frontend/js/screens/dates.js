/**
 * Dates screen: every deadline I found, each next to the sentence it came from.
 * Build 1 shows a plain list. Checking dates one card at a time comes in build 2.
 */
import { listItems, listSyllabi, messageFor } from '../api.js';
import { announce } from '../announce.js';
import { classColorMap } from '../class-colors.js';
import { formatCount, formatDueDateParts, formatWeight, parseDateOnly, plural, typeLabel } from '../format.js';
import { dotted, el, icon } from '../icons.js';

const COPY = {
  heading: "Here's what I found.",
  lead: 'Every deadline, with the sentence I found it in.',
  loading: 'Pulling up your dates…',
  loadFailed: "I couldn't load your dates.",
  noSyllabi: 'No dates yet.',
  noSyllabiText: "Feed me a syllabus and I'll find them.",
  noItems: "I didn't find any dates in your syllabi.",
  undatedNote: "I couldn't pin down one day for these, so I didn't guess.",
  unverified: "I couldn't find this exact sentence in your syllabus. Double-check it.",
  unknownClass: 'Your class',
};

const DATE_PART_CLASS = { weekday: 'due-weekday', monthDay: 'due-day', year: 'due-year', separator: 'due-sep' };
const SKELETON_CARDS = 3;

export function render(container) {
  let disposed = false;
  const heading = el('h1', { tabindex: '-1' }, COPY.heading);
  const body = el('div', { class: 'dates-body' });
  container.append(el('div', { class: 'screen dates-screen' },
    el('header', { class: 'screen-header' }, heading, el('p', { class: 'lead' }, COPY.lead)),
    body));

  const load = async () => {
    body.replaceChildren(loadingView());
    try {
      const [syllabi, items] = await Promise.all([listSyllabi(), listItems()]);
      if (disposed) return;
      const results = resultsView(syllabi, items);
      body.replaceChildren(...results.nodes);
      announce(results.message);
    } catch (error) {
      if (disposed) return;
      const message = messageFor(error);
      const retry = () => {
        heading.focus(); // the Try again button is about to disappear
        load();
      };
      body.replaceChildren(errorView(message, retry));
      announce(`${COPY.loadFailed} ${message}`);
    }
  };

  load();
  return () => {
    disposed = true;
  };
}

/* ---------- States ---------- */

function loadingView() {
  const skeletons = el('ol', { class: 'date-list', role: 'list', 'aria-busy': 'true' });
  for (let i = 0; i < SKELETON_CARDS; i += 1) {
    skeletons.append(el('li', { class: 'date-card skeleton-card', 'aria-hidden': 'true' },
      el('span', { class: 'skeleton skeleton-tags' }),
      el('span', { class: 'skeleton skeleton-title' }),
      el('span', { class: 'skeleton skeleton-when' }),
      el('span', { class: 'skeleton skeleton-source' })));
  }
  return el('div', { class: 'dates-loading' },
    el('p', { class: 'loading-note' }, icon('spinner', 'icon-spin'), el('span', {}, COPY.loading)),
    skeletons);
}

function errorView(message, onRetry) {
  return el('div', { class: 'notice dates-notice' }, icon('alert'),
    el('div', { class: 'notice-body' },
      el('h2', { class: 'notice-title' }, COPY.loadFailed),
      el('p', {}, message),
      el('button', { type: 'button', class: 'button button-secondary', onclick: onRetry }, 'Try again')));
}

function emptyState(title, text, actionLabel) {
  return el('div', { class: 'empty-state' },
    el('span', { class: 'empty-icon' }, icon('calendar')),
    el('h2', {}, title),
    text ? el('p', { class: 'empty-text' }, text) : null,
    el('a', { class: 'button button-primary', href: '#/' }, actionLabel));
}

function resultsView(syllabi, items) {
  if (syllabi.length === 0) {
    return { nodes: [emptyState(COPY.noSyllabi, COPY.noSyllabiText, 'Upload a syllabus')], message: COPY.noSyllabi };
  }
  if (items.length === 0) {
    return { nodes: [emptyState(COPY.noItems, '', 'Add another syllabus')], message: COPY.noItems };
  }

  const context = {
    names: new Map(syllabi.map((syllabus) => [syllabus.id, syllabus.class_name])),
    colors: classColorMap(syllabi),
    nextIndex: 0,
  };
  const dated = [];
  const undated = [];
  for (const item of items) (parseDateOnly(item.due_date) ? dated : undated).push(item);

  const nodes = [];
  if (dated.length) nodes.push(section('dated', 'With a date', 'ol', dated, '', context));
  if (undated.length) nodes.push(section('undated', 'Needs a date', 'ul', undated, COPY.undatedNote, context));
  nodes.push(el('div', { class: 'dates-footer' },
    el('a', { class: 'button button-primary', href: '#/' }, icon('plus'), 'Add another syllabus')));

  const summary = [];
  if (dated.length) summary.push(`${formatCount(dated.length)} with a date`);
  if (undated.length) summary.push(`${formatCount(undated.length)} ${plural(undated.length, 'needs', 'need')} a date`);
  return { nodes, message: summary.join(', ') };
}

function section(id, title, listTag, items, note, context) {
  const headingId = `dates-${id}-heading`;
  return el('section', { class: 'dates-section', 'aria-labelledby': headingId },
    el('h2', { id: headingId }, `${title} (${formatCount(items.length)})`),
    note ? el('p', { class: 'section-note' }, note) : null,
    el(listTag, { class: 'date-list', role: 'list' }, items.map((item) => dateCard(item, context))));
}

/* ---------- One deadline ---------- */

function dateCard(item, context) {
  const color = context.colors.get(item.syllabus_id);
  const chip = el('p', { class: 'class-chip' },
    el('span', { class: 'class-dot', 'aria-hidden': 'true' }),
    el('span', { class: 'class-chip-name' }, context.names.get(item.syllabus_id) ?? COPY.unknownClass));
  if (color) chip.style.setProperty('--class-color', color);

  const meta = [typeLabel(item.type)];
  if (item.weight !== null && item.weight !== undefined) meta.push(formatWeight(item.weight));

  const card = el('li', { class: 'date-card' },
    // The title comes first in reading order so heading navigation lands on it; CSS puts the chip above it.
    el('h3', { class: 'date-card-title' }, item.title),
    el('div', { class: 'date-card-tags' }, chip, el('p', { class: 'date-card-meta' }, dotted(meta))),
    el('div', { class: 'date-card-when' }, whenView(item)),
    el('figure', { class: 'source' },
      el('figcaption', {}, 'From your syllabus'),
      el('blockquote', {}, el('p', {}, item.source_text))),
    item.source_verified ? null : el('p', { class: 'source-warning' }, icon('alert'), el('span', {}, COPY.unverified)));
  card.style.setProperty('--i', String(context.nextIndex));
  context.nextIndex += 1;
  return card;
}

/** The date as <time datetime="2026-10-14">Wed, Oct 14, 2026</time>, or an amber "Needs a date" badge. */
function whenView(item) {
  const parts = formatDueDateParts(item.due_date);
  if (parts.length === 0) {
    return el('p', { class: 'badge badge-warning' }, icon('question'), el('span', {}, 'Needs a date'));
  }
  return el('time', { class: 'due-date', datetime: item.due_date },
    parts.map(({ part, text }) => el('span', { class: DATE_PART_CLASS[part] }, text)));
}

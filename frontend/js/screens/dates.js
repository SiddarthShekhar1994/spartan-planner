/**
 * "Got N dates." Every date is already in, grouped by week. Nothing is confirmed one by one.
 * - An amber box asks only about dates the syllabus doesn't give: Add, or "Not sure yet".
 * - Tapping a row shows its source sentence, with the date words highlighted, and lets the
 *   student change the date.
 * - A sentence that couldn't be found in the syllabus still goes in, with a "Worth a look" flag.
 * - Dates already passed, and items waiting for a date, sit in closed groups at the bottom.
 * Every change is saved on the server and shows a toast with Undo.
 */
import { listItems, listSyllabi, messageFor, saveItemDate } from '../api.js';
import { announce } from '../announce.js';
import { classCode, classColorMap } from '../class-colors.js';
import { formatCount, formatWeekRange, parseDateOnly, plural } from '../format.js';
import { el, icon } from '../icons.js';
import { speaker } from '../speaker.js';
import { toast } from '../toast.js';
import { dayNumber, groupByWeek, localToday } from '../weeks.js';
import { dateRow, needBlock, waitingRow } from './date-row.js';

const COPY = {
  loading: 'Getting your dates…',
  lead: "They're in your plan already. Tap one to see where I found it.",
  loadFailed: "I couldn't load your dates.",
  errorTitle: 'Your dates.',
  none: 'No dates yet.',
  noSyllabi: "Feed me a syllabus and I'll find them.",
  noItems: "I didn't find any dates in your syllabi. If one is a scan, try pasting its text.",
  noneDated: "Your syllabi didn't give me any. Add the ones you know.",
  allPast: 'Nothing coming up. Every date I found has already passed.',
  pickFirst: 'Pick a date first.',
  unknownClass: 'Your class',
};
const SKELETON_ROWS = 4;

export function render(container) {
  let disposed = false;
  let saving = false;
  const state = {
    status: 'loading', error: '', syllabi: [], items: [],
    open: null, opening: null, editing: null, landed: null, arriving: false, pastOpen: false, waitingOpen: false,
    errors: new Map(), drafts: new Map(),
  };
  const heading = el('h1', { tabindex: '-1' }, COPY.loading);
  const lead = el('p', { class: 'lead', hidden: true });
  const body = el('div', { class: 'dates-body' });
  const talk = speaker(heading, lead);
  container.append(el('div', { class: 'screen col' }, talk.root, body));

  /** Move focus to an element by id. False when it isn't on the page. */
  const focusId = (id) => {
    const node = document.getElementById(id);
    node?.focus();
    return node !== null;
  };
  const hasDate = (item) => parseDateOnly(item.due_date) !== null;
  const isPast = (item) => hasDate(item) && dayNumber(parseDateOnly(item.due_date)) < dayNumber(localToday());

  async function load() {
    state.status = 'loading';
    draw();
    try {
      const [syllabi, items] = await Promise.all([listSyllabi(), listItems()]);
      if (disposed) return;
      Object.assign(state, { status: 'ready', syllabi, items, arriving: true });
      draw();
      const waiting = items.filter((item) => !hasDate(item) && item.status !== 'skipped').length;
      announce(waiting ? `${heading.textContent} ${needsTitle(waiting)}.` : heading.textContent);
    } catch (error) {
      if (disposed) return;
      Object.assign(state, { status: 'error', error: messageFor(error) });
      draw();
      announce(`${COPY.loadFailed} ${state.error}`);
    }
  }

  /* ---------- Drawing ---------- */

  function draw() {
    if (state.status === 'loading') return show(COPY.loading, '', [skeleton()], 'reading');
    if (state.status === 'error') return show(COPY.errorTitle, '', [errorNotice()], 'worried');
    if (state.syllabi.length === 0) return show(COPY.none, COPY.noSyllabi, [action('Upload a syllabus', 'btn-primary')]);
    if (state.items.length === 0) return show(COPY.none, COPY.noItems, [action('Add another syllabus', 'btn-primary')]);

    const dated = state.items.filter(hasDate);
    const missing = state.items.filter((item) => !hasDate(item) && item.status !== 'skipped');
    const waiting = state.items.filter((item) => !hasDate(item) && item.status === 'skipped');
    const { weeks, past } = groupByWeek(dated, localToday());
    const count = dated.length;
    const title = count ? `Got ${formatCount(count)} ${plural(count, 'date', 'dates')}.` : COPY.none;

    const landed = state.landed;
    state.landed = null; // the highlight on a row that just changed plays once
    body.classList.toggle('is-arriving', state.arriving); // the groups rise in once, when the dates load
    state.arriving = false;
    return show(title, count ? COPY.lead : COPY.noneDated, [
      missing.length ? needsBox(missing) : null,
      weeks.map(weekSection),
      count && weeks.length === 0 ? el('p', { class: 'note' }, COPY.allPast) : null,
      past.length ? closedGroup('past', 'Already passed', past, dateRow, '') : null,
      waiting.length ? closedGroup('waiting', 'Not sure yet', waiting, waitingRow, "These stay out until they have a date.") : null,
      el('div', { class: 'actions' },
        count ? el('a', { class: 'btn btn-primary', href: '#/plan' }, 'See my plan') : null,
        el('a', { class: count ? 'btn btn-link' : 'btn btn-secondary', href: '#/' }, 'Add another syllabus')),
    ], count ? 'happy' : 'hi', landed);
  }

  function show(title, leadText, nodes, mood = 'hi', landed = null) {
    talk.setMood(mood);
    heading.textContent = title;
    lead.textContent = leadText;
    lead.hidden = !leadText;
    body.replaceChildren(...nodes.flat(Infinity).filter(Boolean));
    state.opening = null; // a row's sentence rises in only when the row was just opened
    if (landed !== null) document.getElementById(`row-${landed}`)?.closest('.drow')?.classList.add('is-landed');
  }

  function skeleton() {
    return el('div', { class: 'dates-loading', 'aria-hidden': 'true' },
      Array.from({ length: SKELETON_ROWS }, () => el('span', { class: 'skeleton skeleton-row' })));
  }

  function errorNotice() {
    const retry = () => {
      heading.focus(); // the Try again button is about to disappear
      load();
    };
    return el('div', { class: 'notice' }, icon('alert'),
      el('div', { class: 'notice-body' },
        el('h2', { class: 'notice-title' }, COPY.loadFailed),
        el('p', {}, state.error),
        el('button', { type: 'button', class: 'btn btn-secondary btn-sm', onclick: retry }, 'Try again')));
  }

  function action(label, kind) {
    return el('div', { class: 'actions' }, el('a', { class: `btn ${kind}`, href: '#/' }, label));
  }

  function needsTitle(count) {
    return count === 1 ? 'One needs a date from you' : `${formatCount(count)} need a date from you`;
  }

  function needsBox(missing) {
    return el('section', { class: 'needs', 'aria-labelledby': 'needs-h' },
      el('h2', { id: 'needs-h' }, icon('alert'), needsTitle(missing.length)),
      missing.map((item) => needBlock(item, context(item))));
  }

  function weekSection(week) {
    const name = week.index === 0 ? 'This week' : week.index === 1 ? 'Next week' : formatWeekRange(week.start);
    return [
      el('h2', { class: 'week-h' }, el('span', {}, name),
        el('span', { class: 'week-count' }, `${formatCount(week.items.length)} due`)),
      el('ul', { class: 'dlist' }, week.items.map((item) => dateRow(item, context(item)))),
    ];
  }

  /** A group that starts closed: dates already passed, or items waiting for a date. */
  function closedGroup(key, name, items, rowBuilder, note) {
    const openKey = `${key}Open`;
    const details = el('details', { class: 'group', open: state[openKey] },
      el('summary', {},
        el('span', { class: 'group-name' }, icon('chevron', 'chev'), name),
        el('span', { class: 'week-count' }, formatCount(items.length))),
      note ? el('p', { class: 'group-note' }, note) : null,
      el('ul', { class: 'dlist' }, items.map((item) => rowBuilder(item, context(item)))));
    details.addEventListener('toggle', () => {
      state[openKey] = details.open;
    });
    return details;
  }

  function context(item) {
    const className = state.syllabi.find((syllabus) => syllabus.id === item.syllabus_id)?.class_name ?? COPY.unknownClass;
    return {
      className,
      code: classCode(className),
      color: classColorMap(state.syllabi).get(item.syllabus_id),
      open: state.open === item.id,
      opening: state.opening === item.id,
      editing: state.editing === item.id,
      error: state.errors.get(item.id) ?? '',
      draft: state.drafts.get(item.id),
      on: {
        toggle: () => toggle(item),
        edit: () => startEdit(item),
        cancel: () => cancelEdit(item),
        save: (value, button) => saveDate(item, value, button),
        skip: (button) => skip(item, button),
        draft: (value) => state.drafts.set(item.id, value),
      },
    };
  }

  /* ---------- Opening a row ---------- */

  function forget(item) {
    state.errors.delete(item.id);
    state.drafts.delete(item.id);
  }

  function toggle(item) {
    state.open = state.open === item.id ? null : item.id;
    state.opening = state.open;
    state.editing = null;
    forget(item);
    draw();
    focusId(`row-${item.id}`);
  }

  function startEdit(item) {
    state.editing = item.id;
    draw();
    focusId(`date-${item.id}`);
  }

  function cancelEdit(item) {
    state.editing = null;
    forget(item);
    draw();
    focusId(`edit-${item.id}`);
  }

  /* ---------- Saving ---------- */

  function replace(saved) {
    state.items = state.items.map((item) => (item.id === saved.id ? saved : item));
  }

  /** Show a row wherever its date now puts it: open, with its group open if it is in one. */
  function reveal(item) {
    state.open = item.id;
    state.opening = item.id;
    state.editing = null;
    if (isPast(item)) state.pastOpen = true;
    if (!hasDate(item) && item.status === 'skipped') state.waitingOpen = true;
  }

  function fail(item, message) {
    state.errors.set(item.id, message);
    draw();
    focusId(`date-${item.id}`);
  }

  /** Send one change. Returns the saved item, or null after showing the error next to the field. */
  async function send(item, change, button) {
    if (saving) return null;
    saving = true;
    const label = button.textContent;
    button.textContent = 'Saving…';
    button.setAttribute('aria-disabled', 'true');
    try {
      const saved = await saveItemDate(item.id, change);
      if (disposed) return null;
      replace(saved);
      forget(item);
      return saved;
    } catch (error) {
      if (disposed) return null;
      button.textContent = label;
      button.removeAttribute('aria-disabled');
      fail(item, messageFor(error));
      return null;
    } finally {
      saving = false;
    }
  }

  /** Undo for any change: put the date and the "Not sure yet" mark back as they were. */
  function undoTo(item, focusAfter) {
    const before = { dueDate: item.due_date, notSure: item.status === 'skipped' };
    return async () => {
      const restored = await saveItemDate(item.id, before);
      if (disposed) return;
      replace(restored);
      state.editing = null;
      if (hasDate(restored)) reveal(restored);
      else state.open = null;
      draw();
      if (!focusId(focusAfter(restored))) heading.focus();
    };
  }

  async function saveDate(item, value, button) {
    if (!value) return fail(item, COPY.pickFirst);
    if (value === item.due_date) return cancelEdit(item);
    const hadDate = hasDate(item);
    const saved = await send(item, { dueDate: value }, button);
    if (!saved) return;
    reveal(saved);
    state.landed = saved.id;
    draw();
    focusId(`row-${saved.id}`);
    toast(hadDate ? 'Date changed.' : `Added ${saved.title}.`,
      undoTo(item, (restored) => (hasDate(restored) || restored.status === 'skipped' ? `row-${restored.id}` : `date-${restored.id}`)));
  }

  async function skip(item, button) {
    const saved = await send(item, { dueDate: null, notSure: true }, button);
    if (!saved) return;
    draw();
    heading.focus();
    toast(`Okay. I'll leave ${saved.title} out until it has a date.`, undoTo(item, (restored) => `date-${restored.id}`));
  }

  load();
  return () => {
    disposed = true;
  };
}

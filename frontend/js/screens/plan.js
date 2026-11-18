/**
 * The plan: a countdown to finals, one "Up next" task with Done and Not today, a gentle
 * warning for the most stacked week with one action, and hours per week by class.
 *
 * PRIVACY: this screen reads the study hours and the extended-time multiplier from the
 * browser and does all the planning math here. It only ever asks the server for the list of
 * classes and dates. It never sends hours, blocks, or what was marked done.
 */
import { listItems, listSyllabi, messageFor } from '../api.js';
import { announce } from '../announce.js';
import { classCode, classColorMap } from '../class-colors.js';
import { formatWeekWords } from '../format.js';
import { el, icon } from '../icons.js';
import { buildPlan, countdownText, daysUntilFinals, hoursText, todayBlocks } from '../plan/build.js';
import { readDay, readEarly, saveDay, saveEarly } from '../plan/day-state.js';
import { readSettings } from '../settings.js';
import { speaker } from '../speaker.js';
import { toast } from '../toast.js';
import { localToday } from '../weeks.js';
import { crunchBox, nextCard, weeksChart } from './plan-parts.js';

const SWAP_MS = 200;
const calmMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const isoDay = ({ year, month, day }) => `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

export function render(container) {
  let disposed = false;
  const today = localToday();
  const date = isoDay(today);
  const settings = readSettings();
  const state = { status: 'loading', error: '', syllabi: [], items: [], day: readDay(date), early: readEarly(), entering: false, grow: true };

  const heading = el('h1', { tabindex: '-1' }, 'Building your plan…');
  const lead = el('p', { class: 'lead', hidden: true });
  const talk = speaker(heading, lead);
  const body = el('div', { class: 'plan-body' });
  container.append(el('div', { class: 'screen' }, el('div', { class: 'plan-head' }, talk.root), body));

  async function load() {
    state.status = 'loading';
    draw();
    try {
      const [syllabi, items] = await Promise.all([listSyllabi(), listItems()]);
      if (disposed) return;
      Object.assign(state, { status: 'ready', syllabi, items });
      draw();
      announce(heading.textContent);
    } catch (error) {
      if (disposed) return;
      Object.assign(state, { status: 'error', error: messageFor(error) });
      draw();
      announce(`I couldn't build your plan. ${state.error}`);
    }
  }

  function show(title, leadText, mood, nodes) {
    talk.setMood(mood);
    heading.textContent = title;
    lead.textContent = leadText;
    lead.hidden = !leadText;
    body.replaceChildren(...nodes.flat(Infinity).filter(Boolean));
  }

  function classes() {
    const colors = classColorMap(state.syllabi);
    return new Map(state.syllabi.map((syllabus) => [syllabus.id, { name: syllabus.class_name, code: classCode(syllabus.class_name), color: colors.get(syllabus.id) }]));
  }

  function makePlan() {
    // "Not sure yet" items have no date, so they stay out on their own; nothing else is filtered.
    return buildPlan({ items: state.items, hours: settings.hours, multiplier: settings.multiplier, today, early: state.early });
  }

  function draw() {
    if (state.status === 'loading') {
      return show('Building your plan…', '', 'reading', [el('div', { class: 'dates-loading', 'aria-hidden': 'true' },
        el('span', { class: 'skeleton skeleton-row' }), el('span', { class: 'skeleton skeleton-row' }))]);
    }
    if (state.status === 'error') {
      const retry = () => { heading.focus(); load(); };
      return show('Your plan.', '', 'worried', [el('div', { class: 'notice' }, icon('alert'),
        el('div', { class: 'notice-body' },
          el('h2', { class: 'notice-title' }, "I couldn't build your plan."), el('p', {}, state.error),
          el('button', { type: 'button', class: 'btn btn-secondary btn-sm', onclick: retry }, 'Try again')))]);
    }
    const plan = makePlan();
    const planned = plan.weeks.some((week) => week.total > 0);
    if (!planned) {
      return show('Your plan.', state.syllabi.length ? 'Nothing is coming up. Add a date or another syllabus.' : "Feed me a syllabus and I'll build it.", 'hi',
        [el('div', { class: 'actions' },
          el('a', { class: 'btn btn-primary', href: '#/' }, state.syllabi.length ? 'Add a syllabus' : 'Upload a syllabus'),
          state.syllabi.length ? el('a', { class: 'btn btn-link', href: '#/dates' }, 'My dates') : null)]);
    }

    const all = todayBlocks(plan);
    const left = all.filter(({ item }) => !state.day.done.has(item.id) && !state.day.moved.has(item.id));
    const doneCount = all.filter(({ item }) => state.day.done.has(item.id)).length;
    const view = { block: left[0] ?? null, doneCount, total: all.length, canReset: all.length > left.length, entering: state.entering };
    state.entering = false;
    const timeWords = plan.multiplier === 1 ? 'regular time' : `${plan.multiplier}x time`;

    show(countdownText(daysUntilFinals(state.items, today)), '', plan.crunch ? 'hi' : 'happy', [
      el('div', { class: state.grow ? 'plan is-growing' : 'plan' },
        nextCard(view, classes(), { done: () => finish('done'), notToday: () => finish('moved'), reset }),
        el('div', { class: 'side' },
          crunchBox(plan, { spread }),
          weeksChart(plan, classes()),
          el('p', { class: 'foot' }, el('span', {}, `${hoursText(plan.hours)} a week · ${timeWords}`),
            el('a', { class: 'btn btn-link btn-sm', href: '#/hours' }, 'Change')))),
    ]);
    state.grow = false; // the bars grow once, when the plan first appears
  }

  const focusId = (id) => document.getElementById(id)?.focus();
  const persistDay = () => saveDay(date, state.day);

  /** Done or Not today on the task that is up next. The card fades out, then the next one fades in. */
  function finish(kind) {
    const plan = makePlan();
    const block = todayBlocks(plan).find(({ item }) => !state.day.done.has(item.id) && !state.day.moved.has(item.id));
    if (!block) return;
    const id = block.item.id;
    const apply = () => {
      if (disposed) return;
      state.day[kind].add(id);
      persistDay();
      state.entering = true;
      draw();
      focusId('next-title');
      toast(kind === 'done' ? 'Nice. One down.' : 'Moved to tomorrow. No harm done.', () => {
        state.day[kind].delete(id);
        persistDay();
        state.entering = true;
        draw();
        focusId('next-title');
      });
    };
    const card = document.getElementById('next-card');
    if (card && !calmMotion()) {
      card.classList.add('is-out');
      window.setTimeout(apply, SWAP_MS);
    } else apply();
  }

  function reset() {
    state.day = { done: new Set(), moved: new Set() };
    persistDay();
    state.entering = true;
    draw();
    focusId('next-title');
  }

  /** Start the suggested item a week sooner, which takes hours out of the stacked week. */
  function spread(item, week) {
    state.early.add(item.id);
    saveEarly(state.early);
    state.grow = true;
    draw();
    focusId('crunch-h');
    const now = makePlan().weeks.find((entry) => entry.start === week.start);
    toast(now ? `Spread out. ${formatWeekWords(week.start)} is now ${hoursText(now.total)}.` : 'Spread out.', () => {
      state.early.delete(item.id);
      saveEarly(state.early);
      state.grow = true;
      draw();
      focusId('crunch-h');
    });
  }

  /** D for Done, N for Not today, unless the student is typing somewhere. */
  function onKey(event) {
    if (event.ctrlKey || event.metaKey || event.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
    const letter = event.key.toLowerCase();
    const button = letter === 'd' ? document.getElementById('next-done') : letter === 'n' ? document.getElementById('next-later') : null;
    if (!button) return;
    event.preventDefault();
    button.click();
  }

  document.addEventListener('keydown', onKey);
  load();
  return () => {
    disposed = true;
    document.removeEventListener('keydown', onKey);
  };
}

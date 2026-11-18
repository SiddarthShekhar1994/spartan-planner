/**
 * The pieces of the plan screen: the "Up next" card, the crunch warning (or the calm note),
 * and the "Your weeks" chart. These only build DOM. Loading, storage and the math are in
 * plan.js and plan/build.js.
 *
 * `classes` is a Map of syllabus id -> {code, name, color}.
 */
import { formatLongDate, formatShortDay, formatWeekWords } from '../format.js';
import { el, icon } from '../icons.js';
import { durationText, hoursText } from '../plan/build.js';

const VERBS = { exam: 'Study for', quiz: 'Study for', essay: 'Write', project: 'Work on', homework: 'Do', reading: 'Read', other: 'Work on' };

const key = (letter) => el('kbd', { class: 'key', 'aria-hidden': 'true' }, letter);

function todayDots(doneCount, total) {
  if (!total) return null;
  return el('span', { class: 'today-dots', role: 'img', 'aria-label': `${doneCount} of ${total} done today` },
    Array.from({ length: total }, (_, index) => el('span', { class: index < doneCount ? 'is-on' : '' })));
}

/**
 * The one thing to do now, under its class tab. With nothing left, a quiet "done for today".
 * @param view {block, doneCount, total, canReset, entering}
 * @param on   {done, notToday, reset}
 */
export function nextCard(view, classes, on) {
  const { block, doneCount, total } = view;
  const cardClass = view.entering ? 'card next is-in' : 'card next';
  const eyebrow = el('p', { class: 'eyebrow' }, el('span', {}, 'Up next · today'), todayDots(doneCount, total));
  if (!block) {
    const line = doneCount ? `${doneCount} ${doneCount === 1 ? 'thing' : 'things'} done. That counts.` : 'Nothing else is planned today.';
    return el('div', { class: 'next-wrap' },
      el('div', { class: 'tab tab-new' }, 'Today'),
      el('div', { class: cardClass, id: 'next-card' }, eyebrow,
        el('h2', { class: 'task', id: 'next-title', tabindex: '-1' }, "You're done for today."),
        el('p', { class: 'next-due' }, line),
        view.canReset ? el('div', { class: 'actions' },
          el('button', { type: 'button', class: 'btn btn-secondary', onclick: on.reset }, 'Bring today back')) : null));
  }
  const { item, hours } = block;
  const klass = classes.get(item.syllabus_id);
  return el('div', { class: 'next-wrap' },
    el('div', { class: 'tab', title: klass?.name, style: klass?.color ? { '--class-color': klass.color } : {} }, klass?.code ?? 'Your class'),
    el('div', { class: cardClass, id: 'next-card' }, eyebrow,
      el('h2', { class: 'task', id: 'next-title', tabindex: '-1' }, `${VERBS[item.type] ?? VERBS.other} ${item.title}`),
      el('p', { class: 'time' }, durationText(hours)),
      el('p', { class: 'next-due' }, `${item.title} is ${formatLongDate(item.due_date)}.`),
      el('div', { class: 'actions' },
        el('button', { type: 'button', class: 'btn btn-primary', id: 'next-done', 'aria-keyshortcuts': 'D', onclick: on.done }, 'Done', key('D')),
        el('button', { type: 'button', class: 'btn btn-secondary', id: 'next-later', 'aria-keyshortcuts': 'N', onclick: on.notToday }, 'Not today', key('N')))));
}

/** "Hey! Dec 7 to 13 is stacked." with the hours against the hours free and one action, or a calm note. */
export function crunchBox(plan, on) {
  const week = plan.crunch;
  if (!week) {
    return el('section', { class: 'calm', 'aria-labelledby': 'crunch-h' },
      el('p', { id: 'crunch-h', tabindex: '-1' }, el('b', {}, 'No stacked weeks.'), ` Everything fits in your ${hoursText(plan.hours)}.`));
  }
  const fix = plan.fix;
  return el('section', { class: 'crunch', 'aria-labelledby': 'crunch-h' },
    el('h2', { id: 'crunch-h', tabindex: '-1' }, `Hey! ${formatWeekWords(week.start)} is stacked.`),
    el('p', {}, `${hoursText(week.total)} of work, ${hoursText(plan.hours)} free.`,
      fix ? ` Starting ${fix.item.title} early would help most.` : ''),
    fix ? el('button', { type: 'button', class: 'btn btn-secondary btn-sm', id: 'spread', onclick: () => on.spread(fix.item, week) }, 'Spread it out for me') : null);
}

function stateLabel(week) {
  if (week.state === 'over') return el('span', { class: 'st is-over' }, icon('alert'), `Over ${Math.round(week.over)}`);
  return el('span', { class: 'st' }, week.state === 'chill' ? 'Chill' : 'Busy');
}

/** Hours per week, stacked by class, with a dashed line at the free hours. Each week also says it in words. */
export function weeksChart(plan, classes) {
  const top = Math.max(plan.hours, ...plan.weeks.map((week) => week.total)) * 1.18;
  const percent = (value, of) => `${((value / of) * 100).toFixed(1)}%`;
  const order = [...classes.keys()].sort((a, b) => a - b);
  const bars = plan.weeks.map((week) => el('div', { class: 'bar', style: { height: percent(week.total, top) } },
    order.filter((id) => (week.byClass.get(id) ?? 0) > 0.05).map((id) => el('span', {
      style: { height: percent(week.byClass.get(id), week.total), background: classes.get(id).color },
    }))));
  const labels = plan.weeks.map((week) => el('li', {},
    el('b', {}, week.index === 0 ? 'This wk' : formatShortDay(week.start)), stateLabel(week),
    el('span', { class: 'muted' }, hoursText(week.total))));
  const used = order.filter((id) => plan.weeks.some((week) => (week.byClass.get(id) ?? 0) > 0.05));
  return el('section', { class: 'card chart', 'aria-labelledby': 'weeks-h' },
    el('h2', { id: 'weeks-h' }, 'Your weeks'),
    el('div', { class: 'bars', 'aria-hidden': 'true' }, bars,
      el('i', { class: 'free-line', style: { bottom: percent(plan.hours, top) } }, el('em', {}, `${hoursText(plan.hours)} free`))),
    el('ul', { class: 'wlabels' }, labels),
    el('ul', { class: 'legend' }, used.map((id) => el('li', {},
      el('span', { class: 'sq', style: { background: classes.get(id).color } }), classes.get(id).code))));
}

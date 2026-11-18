/**
 * The backward plan and the crunch check. Pure functions: no DOM, no storage, no network.
 *
 * PRIVACY: this math uses the extended-time multiplier, so it runs in the browser only.
 * Nothing it returns (hours, blocks, week totals) is ever sent to the server.
 *
 * How it plans:
 * - Each item gets a number of hours by its type, times the multiplier.
 * - Work starts a set number of days before the due date and is spread evenly over the
 *   days in between. An item started "early" begins a week sooner.
 * - Days are whole numbers (see weeks.js). Weeks run Monday to Sunday.
 * - A week is "over" when its hours pass the student's free hours by half an hour or more,
 *   "chill" at half the free hours or less, and "busy" in between.
 */
import { parseDateOnly } from '../format.js';
import { dayNumber, weekStart } from '../weeks.js';

/** Hours of work per item, before the multiplier. Approved by Sid on 2026-11-17 (from the Build 2 prompt). */
export const BASE_HOURS = Object.freeze({ exam: 8, quiz: 2, essay: 6, project: 6, homework: 1.5, reading: 1.5, other: 1.5 });
/** How many days before the due date work starts. */
export const LEAD_DAYS = Object.freeze({ exam: 10, quiz: 3, essay: 7, project: 7, homework: 1, reading: 1, other: 1 });
export const EARLY_EXTRA_DAYS = 7;
export const WEEKS_SHOWN = 5;
const OVER_BY = 0.5;

export const baseHours = (type) => BASE_HOURS[type] ?? BASE_HOURS.other;
export const leadDays = (type) => LEAD_DAYS[type] ?? LEAD_DAYS.other;

/** The day number an item is due, or null when it has no real date. */
export function dueDay(item) {
  const parsed = parseDateOnly(item?.due_date);
  return parsed ? dayNumber(parsed) : null;
}

/**
 * @param {object} input
 * @param {Array}  input.items       items from the server; undated and past ones are left out
 * @param {number} input.hours       free study hours per week
 * @param {number} input.multiplier  extended time: 1, 1.5, 2 ...
 * @param {{year, month, day}} input.today
 * @param {Set<number>} [input.early]  ids of items the student chose to start a week sooner
 * @returns {{hours, multiplier, today, weeks, daily, crunch, fix}}
 *   weeks: [{index, start, total, over, state, byClass: Map(syllabus_id -> hours), byItem: Map(item id -> hours)}]
 *   daily: Map(day number -> [{item, hours}]), soonest due first
 *   crunch: the week furthest over, or null. fix: {item, hours} that would help most to start early, or null.
 */
export function buildPlan({ items, hours, multiplier, today, early = new Set() }) {
  const todayNumber = dayNumber(today);
  const monday = weekStart(todayNumber);
  const free = Math.max(1, Number(hours) || 1);
  const times = Math.max(1, Number(multiplier) || 1);
  const weeks = Array.from({ length: WEEKS_SHOWN }, (_, index) => (
    { index, start: monday + index * 7, total: 0, byClass: new Map(), byItem: new Map() }));
  const daily = new Map();
  const starts = new Map();

  for (const item of items ?? []) {
    const due = dueDay(item);
    if (due === null || due < todayNumber) continue;
    const wanted = due - leadDays(item.type) - (early.has(item.id) ? EARLY_EXTRA_DAYS : 0);
    const start = Math.max(wanted, todayNumber);
    starts.set(item.id, { wanted, start, due });
    const days = Math.max(1, due - start); // the days before the due date; the day itself when it is due today
    const perDay = (baseHours(item.type) * times) / days;
    for (let offset = 0; offset < days; offset += 1) {
      const day = start + offset;
      if (!daily.has(day)) daily.set(day, []);
      daily.get(day).push({ item, hours: perDay, due });
      const week = weeks[Math.floor((day - monday) / 7)];
      if (!week) continue;
      week.total += perDay;
      week.byClass.set(item.syllabus_id, (week.byClass.get(item.syllabus_id) ?? 0) + perDay);
      week.byItem.set(item.id, (week.byItem.get(item.id) ?? 0) + perDay);
    }
  }
  for (const blocks of daily.values()) blocks.sort((a, b) => a.due - b.due);

  for (const week of weeks) {
    week.over = week.total - free;
    week.state = week.over >= OVER_BY ? 'over' : week.total <= free / 2 ? 'chill' : 'busy';
  }
  let last = weeks.length - 1;
  while (last > 0 && weeks[last].total < 0.05) last -= 1;
  const shown = weeks.slice(0, last + 1);

  const crunch = shown.filter((week) => week.state === 'over').sort((a, b) => b.over - a.over)[0] ?? null;
  return { hours: free, multiplier: times, today: todayNumber, weeks: shown, daily, crunch, fix: crunch ? bestFix(crunch, items, starts, early, todayNumber) : null };
}

/** The item in a stacked week with the most hours that could still start sooner. */
function bestFix(week, items, starts, early, todayNumber) {
  const byId = new Map((items ?? []).map((item) => [item.id, item]));
  const candidates = [...week.byItem]
    .map(([id, hours]) => ({ item: byId.get(id), hours, timing: starts.get(id) }))
    // "Can still start sooner" means its usual start day hasn't arrived yet.
    .filter(({ item, timing }) => item && !early.has(item.id) && timing.wanted > todayNumber);
  candidates.sort((a, b) => b.hours - a.hours);
  return candidates.length ? { item: candidates[0].item, hours: candidates[0].hours } : null;
}

/** Today's blocks, soonest due first. */
export function todayBlocks(plan) {
  return plan.daily.get(plan.today) ?? [];
}

/** Days until the first final (an exam with "final" in its title), else the first exam. Null when there is none ahead. */
export function daysUntilFinals(items, today) {
  const todayNumber = dayNumber(today);
  const exams = (items ?? []).filter((item) => item.type === 'exam').map((item) => ({ item, due: dueDay(item) }))
    .filter(({ due }) => due !== null && due >= todayNumber);
  const finals = exams.filter(({ item }) => /final/i.test(item.title));
  const pool = finals.length ? finals : exams;
  return pool.length ? Math.min(...pool.map(({ due }) => due)) - todayNumber : null;
}

/** "4 weeks until finals." / "9 days until finals." / "Finals start tomorrow." / "Finals are here." / "Your plan." */
export function countdownText(days) {
  if (days === null || days === undefined) return 'Your plan.';
  if (days > 13) return `${Math.round(days / 7)} weeks until finals.`;
  if (days > 1) return `${days} days until finals.`;
  return days === 1 ? 'Finals start tomorrow.' : 'Finals are here.';
}

/** 1.5 -> "1 hr 30 min". Rounded to 15 minutes, never less than 15. */
export function durationText(hours) {
  const minutes = Math.max(15, Math.round(((Number(hours) || 0) * 60) / 15) * 15);
  const whole = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return [whole ? `${whole} ${whole === 1 ? 'hr' : 'hrs'}` : '', rest ? `${rest} min` : ''].filter(Boolean).join(' ');
}

/** 20.6 -> "21 hrs", 0.4 -> "under 1 hr". */
export function hoursText(hours) {
  const rounded = Math.round(hours);
  if (hours > 0 && rounded < 1) return 'under 1 hr';
  return `${rounded} ${rounded === 1 ? 'hr' : 'hrs'}`;
}

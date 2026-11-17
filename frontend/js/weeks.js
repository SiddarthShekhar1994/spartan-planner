/**
 * Sorting dates into weeks. Pure functions: no DOM, no clock unless you pass one.
 *
 * A due date is a calendar day with no time attached. Days are counted as whole numbers
 * (days since 1970-01-01), so nothing here depends on a time zone or on daylight saving.
 * Weeks run Monday to Sunday.
 */
import { parseDateOnly } from './format.js';

const DAY_MS = 86400000;

/** {year, month, day} -> days since 1970-01-01. */
export function dayNumber({ year, month, day }) {
  return Math.round(Date.UTC(year, month - 1, day) / DAY_MS);
}

/** Today in the browser's own time zone, as {year, month, day}. */
export function localToday(now = new Date()) {
  return { year: now.getFullYear(), month: now.getMonth() + 1, day: now.getDate() };
}

/** The Monday on or before a day number. 1970-01-01 was a Thursday. */
export function weekStart(day) {
  return day - ((((day + 3) % 7) + 7) % 7);
}

/**
 * Split dated items into upcoming weeks and dates that have passed.
 *
 * @param {Array<{due_date: string}>} items  items without a real date are left out
 * @param {{year: number, month: number, day: number}} today
 * @returns {{weeks: Array<{index: number, start: number, items: Array}>, past: Array}}
 *   weeks: soonest first; index 0 is this week, 1 is next week. Items inside a week are in date order.
 *   past: every item due before today, most recent first.
 */
export function groupByWeek(items, today) {
  const todayNumber = dayNumber(today);
  const thisMonday = weekStart(todayNumber);
  const dated = [];
  for (const item of items ?? []) {
    const parsed = parseDateOnly(item?.due_date);
    if (parsed) dated.push({ item, day: dayNumber(parsed) });
  }
  dated.sort((a, b) => a.day - b.day); // Array.prototype.sort is stable, so ties keep their order

  const weeks = new Map();
  const past = [];
  for (const { item, day } of dated) {
    if (day < todayNumber) {
      past.push(item);
      continue;
    }
    const start = weekStart(day);
    if (!weeks.has(start)) weeks.set(start, { index: (start - thisMonday) / 7, start, items: [] });
    weeks.get(start).items.push(item);
  }
  past.reverse();
  return { weeks: [...weeks.values()], past };
}

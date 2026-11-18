/**
 * What the student has done with today's tasks (Done, Not today) and which items they chose
 * to start a week early. Kept in this browser's localStorage only: item ids, never hours.
 * "Done" and "Not today" belong to one day, so they reset when the date changes.
 */

const DAY_KEY = 'spartan.planDay';
const EARLY_KEY = 'spartan.planEarly';

function read(key) {
  try {
    return JSON.parse(window.localStorage.getItem(key) || 'null');
  } catch {
    return null; // storage blocked, or the saved value is damaged
  }
}

function write(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage is blocked or full. The choice still holds until the page is closed.
  }
}

const ids = (value) => new Set(Array.isArray(value) ? value.filter(Number.isInteger) : []);

/** {done: Set, moved: Set} for this date ("2026-11-17"). Another day's saved state is ignored. */
export function readDay(date) {
  const saved = read(DAY_KEY);
  const mine = saved && saved.date === date ? saved : {};
  return { done: ids(mine.done), moved: ids(mine.moved) };
}

export function saveDay(date, { done, moved }) {
  write(DAY_KEY, { date, done: [...done], moved: [...moved] });
}

/** Ids of items the student chose to start a week sooner. */
export function readEarly() {
  return ids(read(EARLY_KEY));
}

export function saveEarly(early) {
  write(EARLY_KEY, [...early]);
}

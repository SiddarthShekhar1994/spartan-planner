import assert from 'node:assert/strict';
import { test } from 'node:test';

import { dayNumber, groupByWeek, localToday, weekStart } from '../../frontend/js/weeks.js';

const item = (title, due_date) => ({ title, due_date });
const titles = (items) => items.map((entry) => entry.title);
const TUESDAY = { year: 2026, month: 11, day: 17 }; // Tue, Nov 17, 2026

test('dayNumber counts whole days from 1970-01-01', () => {
  assert.equal(dayNumber({ year: 1970, month: 1, day: 1 }), 0);
  assert.equal(dayNumber({ year: 1970, month: 1, day: 2 }), 1);
  assert.equal(dayNumber({ year: 2026, month: 11, day: 17 }) - dayNumber({ year: 2026, month: 11, day: 16 }), 1);
});

test('a day number does not shift across the daylight saving change', () => {
  // Nov 1, 2026 is the US fall-back day: 25 hours long in local time.
  assert.equal(dayNumber({ year: 2026, month: 11, day: 2 }) - dayNumber({ year: 2026, month: 10, day: 31 }), 2);
});

test('weekStart is the Monday on or before the day', () => {
  const monday = dayNumber({ year: 2026, month: 11, day: 16 });
  for (let offset = 0; offset < 7; offset += 1) assert.equal(weekStart(monday + offset), monday);
  assert.equal(weekStart(monday - 1), monday - 7);
  assert.equal(weekStart(dayNumber({ year: 1969, month: 12, day: 31 })), dayNumber({ year: 1969, month: 12, day: 29 }));
});

test('localToday reads the local calendar day', () => {
  assert.deepEqual(localToday(new Date(2026, 10, 17, 23, 59)), { year: 2026, month: 11, day: 17 });
  assert.deepEqual(localToday(new Date(2026, 0, 1, 0, 0)), { year: 2026, month: 1, day: 1 });
});

test('dates are grouped Monday to Sunday, soonest week first', () => {
  const { weeks, past } = groupByWeek([
    item('Final exam', '2026-12-14'),
    item('Quiz 6', '2026-11-19'),
    item('Essay 3 draft', '2026-11-22'), // Sunday, still this week
    item('Homework 7', '2026-11-23'), // Monday, next week
    item('Lab practical 2', '2026-12-02'),
  ], TUESDAY);
  assert.deepEqual(past, []);
  assert.deepEqual(weeks.map((week) => week.index), [0, 1, 2, 4]);
  assert.deepEqual(weeks.map((week) => titles(week.items)), [
    ['Quiz 6', 'Essay 3 draft'], ['Homework 7'], ['Lab practical 2'], ['Final exam'],
  ]);
  assert.equal(weeks[0].start, dayNumber({ year: 2026, month: 11, day: 16 }));
  assert.equal(weeks[3].start, dayNumber({ year: 2026, month: 12, day: 14 }));
});

test('today is upcoming; yesterday has passed, even inside this week', () => {
  const { weeks, past } = groupByWeek([
    item('Due today', '2026-11-17'),
    item('Due yesterday', '2026-11-16'),
  ], TUESDAY);
  assert.deepEqual(titles(weeks[0].items), ['Due today']);
  assert.deepEqual(titles(past), ['Due yesterday']);
});

test('passed dates come back most recent first', () => {
  const { weeks, past } = groupByWeek([
    item('Quiz 1', '2026-09-10'),
    item('Midterm', '2026-10-14'),
    item('Essay 1', '2026-10-02'),
  ], TUESDAY);
  assert.deepEqual(weeks, []);
  assert.deepEqual(titles(past), ['Midterm', 'Essay 1', 'Quiz 1']);
});

test('two items on the same day keep the order they came in', () => {
  const { weeks } = groupByWeek([item('B', '2026-11-20'), item('A', '2026-11-20')], TUESDAY);
  assert.deepEqual(titles(weeks[0].items), ['B', 'A']);
});

test('items without a real date are left out, never guessed', () => {
  const { weeks, past } = groupByWeek([
    item('No date', null),
    item('Not a day', '2026-02-30'),
    item('Wrong shape', '11/20/2026'),
    item('Missing', undefined),
    item('Real', '2026-11-20'),
  ], TUESDAY);
  assert.deepEqual(titles(weeks.flatMap((week) => week.items)), ['Real']);
  assert.deepEqual(past, []);
  assert.deepEqual(groupByWeek(null, TUESDAY), { weeks: [], past: [] });
});

test('a week that spans New Year stays one week', () => {
  const { weeks } = groupByWeek([item('A', '2026-12-31'), item('B', '2027-01-03')], { year: 2026, month: 12, day: 28 });
  assert.equal(weeks.length, 1);
  assert.equal(weeks[0].index, 0);
});

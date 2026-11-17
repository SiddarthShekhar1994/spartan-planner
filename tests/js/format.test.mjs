import assert from 'node:assert/strict';
import { test } from 'node:test';

import { classCode, classColorMap, colorForIndex } from '../../frontend/js/class-colors.js';
import { formatDayParts, formatLongDate, formatWeekRange, parseDateOnly } from '../../frontend/js/format.js';
import { dayNumber } from '../../frontend/js/weeks.js';

test('a due date is split into weekday, day and month', () => {
  assert.deepEqual(formatDayParts('2026-11-19'), { weekday: 'Thu', day: '19', month: 'Nov' });
  assert.deepEqual(formatDayParts('2026-12-02'), { weekday: 'Wed', day: '2', month: 'Dec' });
  assert.equal(formatDayParts('2026-02-30'), null);
  assert.equal(formatDayParts(null), null);
});

test('the long date names the weekday and the year', () => {
  assert.equal(formatLongDate('2026-11-19'), 'Thursday, November 19, 2026');
  assert.equal(formatLongDate('nope'), '');
});

test('a date never slips to the day before', () => {
  // new Date("2026-11-01") in California is Oct 31 local time. These must not be.
  assert.deepEqual(formatDayParts('2026-11-01'), { weekday: 'Sun', day: '1', month: 'Nov' });
  assert.deepEqual(parseDateOnly('2026-11-01'), { year: 2026, month: 11, day: 1 });
});

test('a week is named by its Monday and Sunday', () => {
  const plain = (text) => text.replace(/\s+/g, ' ');
  assert.equal(plain(formatWeekRange(dayNumber({ year: 2026, month: 11, day: 30 }))), 'Nov 30 – Dec 6');
  assert.equal(plain(formatWeekRange(dayNumber({ year: 2026, month: 12, day: 7 }))), 'Dec 7 – 13');
});

test('a class chip shows the course code when the name starts with one', () => {
  assert.equal(classCode('CS 146: Data Structures and Algorithms'), 'CS 146');
  assert.equal(classCode('ENGL 100A - Writing Workshop'), 'ENGL 100A');
  assert.equal(classCode('cs101'), 'CS 101');
  assert.equal(classCode('  biol-30 fall'), 'BIOL 30');
  assert.equal(classCode('Math 30'), 'MATH 30');
});

test('a name without a course code is shown whole', () => {
  for (const name of ['Pasted syllabus', 'History of Art', 'Fall 2026 syllabus', 'Section 12345', 'A 1']) {
    assert.equal(classCode(name), name);
  }
  assert.equal(classCode(null), '');
});

test('class colors follow the order classes were added, then cycle', () => {
  const colors = classColorMap([{ id: 9 }, { id: 2 }, { id: 5 }, { id: 11 }]);
  assert.deepEqual([2, 5, 9, 11].map((id) => colors.get(id)), ['#7AA2FF', '#FF8FB1', '#6EE7B7', '#7AA2FF']);
  assert.equal(colorForIndex(3), colorForIndex(0));
});

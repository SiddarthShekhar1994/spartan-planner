import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  baseHours, buildPlan, countdownText, daysUntilFinals, durationText, hoursText, leadDays, todayBlocks,
} from '../../frontend/js/plan/build.js';
import { dayNumber } from '../../frontend/js/weeks.js';

const TODAY = { year: 2026, month: 11, day: 17 }; // Tuesday. This week's Monday is Nov 16.
let nextId = 1;
const item = (title, type, due_date, syllabus_id = 1) => ({ id: nextId++, title, type, due_date, syllabus_id, status: 'unchecked' });
const plan = (items, extra = {}) => buildPlan({ items, hours: 12, multiplier: 1, today: TODAY, ...extra });
const sum = (values) => [...values].reduce((total, value) => total + value, 0);
const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} is not ${expected}`);

test('hours and lead days come from the item type', () => {
  assert.deepEqual(['exam', 'quiz', 'essay', 'project', 'homework', 'reading', 'other'].map(baseHours), [8, 2, 6, 6, 1.5, 1.5, 1.5]);
  assert.deepEqual(['exam', 'quiz', 'essay', 'project', 'homework', 'reading', 'other'].map(leadDays), [10, 3, 7, 7, 1, 1, 1]);
  assert.equal(baseHours('mystery'), 1.5);
  assert.equal(leadDays(undefined), 1);
});

test('an exam is spread over the ten days before it', () => {
  const exam = item('Final exam', 'exam', '2026-12-14');
  const result = plan([exam]);
  const days = [...result.daily.keys()].sort((a, b) => a - b);
  assert.equal(days.length, 10);
  assert.equal(days[0], dayNumber({ year: 2026, month: 12, day: 4 }));
  assert.equal(days[9], dayNumber({ year: 2026, month: 12, day: 13 }));
  near(sum([...result.daily.values()].map((blocks) => blocks[0].hours)), 8);
});

test('the multiplier scales every hour, and never reaches below regular time', () => {
  const quiz = item('Quiz 6', 'quiz', '2026-11-19');
  near(sum(plan([quiz], { multiplier: 1.5 }).weeks.map((week) => week.total)), 3);
  near(sum(plan([quiz], { multiplier: 2 }).weeks.map((week) => week.total)), 4);
  near(sum(plan([quiz], { multiplier: 0.5 }).weeks.map((week) => week.total)), 2);
});

test('work that should have started already is squeezed into the days left', () => {
  const exam = item('Midterm', 'exam', '2026-11-20'); // 10 days back is Nov 10; today is Nov 17
  const result = plan([exam]);
  assert.deepEqual([...result.daily.keys()].sort((a, b) => a - b), [17, 18, 19].map((day) => dayNumber({ year: 2026, month: 11, day })));
  near(todayBlocks(result)[0].hours, 8 / 3);
});

test('something due today is today\'s work; past and undated items are left out', () => {
  const dueToday = item('Homework 9', 'homework', '2026-11-17');
  const result = plan([dueToday, item('Old quiz', 'quiz', '2026-11-10'), item('TBA', 'project', null), item('Bad', 'exam', '2026-02-30')]);
  assert.deepEqual(todayBlocks(result).map((block) => block.item.title), ['Homework 9']);
  near(sum(result.weeks.map((week) => week.total)), 1.5);
});

test('today\'s blocks come soonest due first', () => {
  const result = plan([item('Essay', 'essay', '2026-11-23'), item('Quiz', 'quiz', '2026-11-18')]);
  assert.deepEqual(todayBlocks(result).map((block) => block.item.title), ['Quiz', 'Essay']);
});

test('weeks run Monday to Sunday and split hours by class', () => {
  const result = plan([item('Essay', 'essay', '2026-11-25', 1), item('Quiz', 'quiz', '2026-11-19', 2)]);
  // Essay: 6 hrs over Nov 18..24 = 5 days this week (18-22) and 2 next week (23-24).
  near(result.weeks[0].byClass.get(1), (6 / 7) * 5);
  near(result.weeks[1].byClass.get(1), (6 / 7) * 2);
  near(result.weeks[0].byClass.get(2), 2);
  assert.equal(result.weeks[0].start, dayNumber({ year: 2026, month: 11, day: 16 }));
  assert.equal(result.weeks.length, 2, 'empty weeks at the end are dropped');
});

test('a week is chill, busy or over against the free hours', () => {
  const exam = item('Exam', 'exam', '2026-11-23'); // 8 hrs over Nov 17..22: all this week
  assert.equal(plan([exam], { hours: 16 }).weeks[0].state, 'chill');
  assert.equal(plan([exam], { hours: 12 }).weeks[0].state, 'busy');
  assert.equal(plan([exam], { hours: 8 }).weeks[0].state, 'busy', 'exactly the free hours is not over');
  assert.equal(plan([exam], { hours: 7 }).weeks[0].state, 'over');
  assert.equal(plan([exam], { hours: 12 }).crunch, null);
});

test('the crunch is the week furthest over, and the fix is its biggest item that can still start sooner', () => {
  const items = [
    item('Final exam', 'exam', '2026-12-14', 1), item('Bio final', 'exam', '2026-12-14', 2),
    item('Portfolio', 'project', '2026-12-13', 3), item('Quiz', 'quiz', '2026-12-11', 1),
  ];
  const result = plan(items, { hours: 10 });
  assert.ok(result.crunch, 'a week is over');
  assert.equal(result.crunch.start, dayNumber({ year: 2026, month: 12, day: 7 }));
  assert.equal(result.fix.item.title, 'Final exam', 'the item with the most hours in that week');

  const spread = plan(items, { hours: 10, early: new Set([result.fix.item.id]) });
  const before = result.weeks.find((week) => week.start === result.crunch.start).total;
  const after = spread.weeks.find((week) => week.start === result.crunch.start).total;
  assert.ok(after < before, 'starting it a week sooner takes hours out of the stacked week');
  near(sum(spread.weeks.map((week) => week.total)), sum(result.weeks.map((week) => week.total)));
});

test('nothing to plan gives one empty week and no crunch', () => {
  const result = plan([]);
  assert.equal(result.weeks.length, 1);
  assert.equal(result.weeks[0].total, 0);
  assert.equal(result.weeks[0].state, 'chill');
  assert.equal(result.crunch, null);
  assert.equal(result.fix, null);
  assert.deepEqual(todayBlocks(result), []);
});

test('the countdown goes to the first final, or the first exam when none is called a final', () => {
  const items = [item('Midterm 2', 'exam', '2026-12-03'), item('Final exam', 'exam', '2026-12-14'), item('Final exam', 'exam', '2026-12-16'), item('Final project', 'project', '2026-12-01')];
  assert.equal(daysUntilFinals(items, TODAY), 27);
  assert.equal(daysUntilFinals([items[0]], TODAY), 16);
  assert.equal(daysUntilFinals([item('Old final', 'exam', '2026-05-20')], TODAY), null);
  assert.equal(daysUntilFinals([], TODAY), null);
});

test('the countdown reads in weeks, then days', () => {
  assert.equal(countdownText(27), '4 weeks until finals.');
  assert.equal(countdownText(14), '2 weeks until finals.');
  assert.equal(countdownText(13), '13 days until finals.');
  assert.equal(countdownText(2), '2 days until finals.');
  assert.equal(countdownText(1), 'Finals start tomorrow.');
  assert.equal(countdownText(0), 'Finals are here.');
  assert.equal(countdownText(null), 'Your plan.');
});

test('hours read as short words', () => {
  assert.equal(durationText(1.5), '1 hr 30 min');
  assert.equal(durationText(2), '2 hrs');
  assert.equal(durationText(0.8), '45 min');
  assert.equal(durationText(0.05), '15 min');
  assert.equal(durationText(8 / 3), '2 hrs 45 min');
  assert.equal(hoursText(20.6), '21 hrs');
  assert.equal(hoursText(1), '1 hr');
  assert.equal(hoursText(0.4), 'under 1 hr');
  assert.equal(hoursText(0), '0 hrs');
});

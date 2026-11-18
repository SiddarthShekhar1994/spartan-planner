import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  cleanHours, cleanMultiplier, HOURS_KEY, MULTIPLIER_KEY, perDayText, readSettings, saveHours, saveMultiplier,
} from '../../frontend/js/settings.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

/** A stand-in for localStorage. */
function fakeStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    data,
  };
}

test('hours must be a whole number from 1 to 40', () => {
  assert.equal(cleanHours('12'), 12);
  assert.equal(cleanHours(1), 1);
  assert.equal(cleanHours(40), 40);
  for (const bad of [0, 41, -3, 12.5, '', null, undefined, 'lots', NaN, Infinity]) assert.equal(cleanHours(bad), null);
});

test('the multiplier must be a number from 1 to 4', () => {
  assert.equal(cleanMultiplier('1'), 1);
  assert.equal(cleanMultiplier('1.5'), 1.5);
  assert.equal(cleanMultiplier(2), 2);
  assert.equal(cleanMultiplier('1.25'), 1.25);
  assert.equal(cleanMultiplier(4), 4);
  assert.equal(cleanMultiplier('1.333333'), 1.33);
  for (const bad of [0, 0.99, 4.01, 9, -1, '', '   ', null, undefined, 'double', NaN, Infinity]) {
    assert.equal(cleanMultiplier(bad), null);
  }
});

test('with nothing saved, the defaults are 12 hours and regular time', () => {
  assert.deepEqual(readSettings(fakeStorage()), { hours: 12, multiplier: 1 });
});

test('saved answers come back, and a damaged value falls back to the default', () => {
  const storage = fakeStorage();
  assert.equal(saveHours('15', storage), true);
  assert.equal(saveMultiplier('1.5', storage), true);
  assert.deepEqual(readSettings(storage), { hours: 15, multiplier: 1.5 });
  assert.deepEqual(readSettings(fakeStorage({ [HOURS_KEY]: 'abc', [MULTIPLIER_KEY]: '99' })), { hours: 12, multiplier: 1 });
});

test('a value out of range is not saved', () => {
  const storage = fakeStorage({ [MULTIPLIER_KEY]: '2' });
  assert.equal(saveMultiplier('9', storage), false);
  assert.equal(saveHours('0', storage), false);
  assert.equal(storage.data.get(MULTIPLIER_KEY), '2');
  assert.equal(storage.data.has(HOURS_KEY), false);
});

test('storage that throws does not break the screens', () => {
  const broken = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
  assert.deepEqual(readSettings(broken), { hours: 12, multiplier: 1 });
  assert.equal(saveHours(10, broken), true);
});

test('hours a week reads as time a day', () => {
  assert.equal(perDayText(12), '1 hr 45 min');
  assert.equal(perDayText(7), '1 hr');
  assert.equal(perDayText(14), '2 hrs');
  assert.equal(perDayText(1), '10 min');
  assert.equal(perDayText(40), '5 hrs 45 min');
  assert.equal(perDayText(0), 'a few minutes');
});

/* ---------- Privacy: the answers never leave the browser ---------- */

function jsFiles(folder) {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const path = join(folder, entry.name);
    if (entry.isDirectory()) return jsFiles(path);
    return entry.name.endsWith('.js') ? [path] : [];
  });
}

test('the module that talks to the server knows nothing about the setup answers', () => {
  const api = readFileSync(join(ROOT, 'frontend', 'js', 'api.js'), 'utf8');
  for (const word of ['settings.js', 'multiplier', 'freeHours', 'readSettings', 'localStorage']) {
    assert.equal(api.includes(word), false, `api.js mentions ${word}`);
  }
});

test('only the setup screens and the plan read the setup answers', () => {
  const allowed = new Set(['hours.js', 'extra.js', 'plan.js']);
  const importers = jsFiles(join(ROOT, 'frontend', 'js'))
    .filter((path) => /from\s+['"][^'"]*settings\.js['"]/.test(readFileSync(path, 'utf8')))
    .map((path) => path.split(/[\\/]/).pop());
  for (const name of importers) assert.ok(allowed.has(name), `${name} imports settings.js`);
});

test('no screen that reads the setup answers also calls the server', () => {
  for (const name of ['hours.js', 'extra.js']) {
    const source = readFileSync(join(ROOT, 'frontend', 'js', 'screens', name), 'utf8');
    assert.equal(/api\.js|fetch\(|XMLHttpRequest|sendBeacon/.test(source), false, `${name} can reach the server`);
  }
});

test('the plan screen only reads from the server: it has no way to send anything', () => {
  const source = readFileSync(join(ROOT, 'frontend', 'js', 'screens', 'plan.js'), 'utf8');
  const fromApi = /import\s*\{([^}]*)\}\s*from\s*'\.\.\/api\.js'/.exec(source);
  assert.ok(fromApi, 'plan.js imports from api.js');
  const names = fromApi[1].split(',').map((name) => name.trim()).filter(Boolean).sort();
  assert.deepEqual(names, ['listItems', 'listSyllabi', 'messageFor']);
  assert.equal(/fetch\(|XMLHttpRequest|sendBeacon|request\(/.test(source), false);
  for (const name of ['build.js', 'day-state.js']) {
    const helper = readFileSync(join(ROOT, 'frontend', 'js', 'plan', name), 'utf8');
    assert.equal(/api\.js|fetch\(|XMLHttpRequest|sendBeacon/.test(helper), false, `${name} can reach the server`);
  }
});

test('the server has no word for the multiplier or free hours', () => {
  const folder = join(ROOT, 'backend');
  const python = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === '__pycache__' ? [] : python(path);
    return /\.(py|sql)$/.test(entry.name) ? [path] : [];
  });
  for (const path of python(folder)) {
    // Comments that say "never add a column for the multiplier" are fine; code and SQL columns are not.
    const code = readFileSync(path, 'utf8').split('\n').filter((line) => !/^\s*(#|--|""")/.test(line) && !/never|Never/.test(line)).join('\n');
    assert.equal(/multiplier|free_hours|freeHours/i.test(code), false, `${path} mentions a private setting`);
  }
});

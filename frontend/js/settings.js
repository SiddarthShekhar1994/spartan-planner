/**
 * The two setup answers: free study hours per week and the extended-time multiplier.
 *
 * PRIVACY: both live only in this browser's localStorage. They are never put in a request
 * body, a query string or a header, and the server has no column for them. api.js must never
 * import this module. All planning math that uses them runs in the browser.
 */

export const HOURS_KEY = 'spartan.freeHours';
export const MULTIPLIER_KEY = 'spartan.multiplier';

export const MIN_HOURS = 1;
export const MAX_HOURS = 40;
export const DEFAULT_HOURS = 12;
export const MIN_MULTIPLIER = 1;
export const MAX_MULTIPLIER = 4;
export const DEFAULT_MULTIPLIER = 1;
/** The choices shown as big buttons. Anything else is "Other". */
export const PRESET_MULTIPLIERS = Object.freeze([1, 1.5, 2]);

/** A whole number of hours from 1 to 40, or null. */
export function cleanHours(value) {
  if (value === null || value === undefined || value === '') return null;
  const hours = Number(value);
  return Number.isInteger(hours) && hours >= MIN_HOURS && hours <= MAX_HOURS ? hours : null;
}

/** A multiplier from 1 to 4 (two decimals at most), or null. */
export function cleanMultiplier(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  const multiplier = Number(value);
  if (!Number.isFinite(multiplier) || multiplier < MIN_MULTIPLIER || multiplier > MAX_MULTIPLIER) return null;
  return Math.round(multiplier * 100) / 100;
}

function storageOrNull(storage) {
  if (storage) return storage;
  try {
    return window.localStorage;
  } catch {
    return null; // blocked, as in some private windows
  }
}

function read(storage, key) {
  try {
    return storageOrNull(storage)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function write(storage, key, value) {
  try {
    storageOrNull(storage)?.setItem(key, String(value));
  } catch {
    // Storage is blocked or full. The answer still holds for this visit's screens.
  }
}

/** {hours, multiplier}: what was saved, or the defaults (12 hours, regular time). */
export function readSettings(storage = null) {
  return {
    hours: cleanHours(read(storage, HOURS_KEY)) ?? DEFAULT_HOURS,
    multiplier: cleanMultiplier(read(storage, MULTIPLIER_KEY)) ?? DEFAULT_MULTIPLIER,
  };
}

/** Save the hours. Returns false (and saves nothing) when the value isn't 1 to 40. */
export function saveHours(value, storage = null) {
  const hours = cleanHours(value);
  if (hours === null) return false;
  write(storage, HOURS_KEY, hours);
  return true;
}

/** Save the multiplier. Returns false (and saves nothing) when the value isn't 1 to 4. */
export function saveMultiplier(value, storage = null) {
  const multiplier = cleanMultiplier(value);
  if (multiplier === null) return false;
  write(storage, MULTIPLIER_KEY, multiplier);
  return true;
}

/** 12 hours a week -> "1 hr 45 min", for "About 1 hr 45 min a day." Rounded to 5 minutes. */
export function perDayText(hours) {
  const minutes = Math.round((((Number(hours) || 0) / 7) * 60) / 5) * 5;
  const whole = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const parts = [];
  if (whole) parts.push(`${whole} ${whole === 1 ? 'hr' : 'hrs'}`);
  if (rest) parts.push(`${rest} min`);
  return parts.join(' ') || 'a few minutes';
}

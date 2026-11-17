/**
 * Formatting for dates, numbers and labels. Everything goes through Intl, in en-US.
 *
 * Due dates are calendar days with no time attached. They are formatted in UTC from
 * Date.UTC(...), never with new Date("YYYY-MM-DD") in local time, so a student in
 * California never sees the day before.
 */

const LOCALE = 'en-US';

const dueDateFormat = new Intl.DateTimeFormat(LOCALE, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  timeZone: 'UTC',
});
const utc = (options) => new Intl.DateTimeFormat(LOCALE, { ...options, timeZone: 'UTC' });
const weekdayShortFormat = utc({ weekday: 'short' });
const monthShortFormat = utc({ month: 'short' });
const dayFormat = utc({ day: 'numeric' });
const monthDayFormat = utc({ month: 'short', day: 'numeric' });
const longDateFormat = utc({ weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
const DAY_MS = 86400000;
const percentFormat = new Intl.NumberFormat(LOCALE, { style: 'percent', maximumFractionDigits: 1 });
const countFormat = new Intl.NumberFormat(LOCALE);
const pluralRules = new Intl.PluralRules(LOCALE);

const TYPE_LABELS = new Map([
  ['exam', 'Exam'],
  ['quiz', 'Quiz'],
  ['project', 'Project'],
  ['essay', 'Essay'],
  ['homework', 'Homework'],
  ['reading', 'Reading'],
  ['other', 'Other'],
]);

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** "2026-10-14" -> {year: 2026, month: 10, day: 14}. Null unless it's a real calendar day. */
export function parseDateOnly(iso) {
  if (typeof iso !== 'string') return null;
  const match = ISO_DATE.exec(iso);
  if (!match) return null;
  const [year, month, day] = match.slice(1).map(Number);
  const probe = new Date(Date.UTC(year, month - 1, day));
  const isReal =
    probe.getUTCFullYear() === year && probe.getUTCMonth() === month - 1 && probe.getUTCDate() === day;
  return isReal ? { year, month, day } : null;
}

function utcTime({ year, month, day }) {
  return Date.UTC(year, month - 1, day);
}

/** "2026-10-14" -> "Wed, Oct 14, 2026". Empty string for a missing or malformed date. */
export function formatDueDate(iso) {
  const parsed = parseDateOnly(iso);
  return parsed ? dueDateFormat.format(utcTime(parsed)) : '';
}

/**
 * The same text as formatDueDate, split into labeled pieces for styling:
 * [{part: "weekday", text: "Wed"}, {part: "separator", text: ", "}, {part: "monthDay", text: "Oct 14"},
 *  {part: "separator", text: ", "}, {part: "year", text: "2026"}].
 * Joining every piece's text gives exactly formatDueDate(iso). Empty array for a bad date.
 */
export function formatDueDateParts(iso) {
  const parsed = parseDateOnly(iso);
  if (!parsed) return [];
  const kindOf = (type) => {
    if (type === 'month' || type === 'day') return 'monthDay';
    return type === 'weekday' || type === 'year' ? type : 'separator';
  };
  const pieces = dueDateFormat.formatToParts(utcTime(parsed)).map(({ type, value }) => ({ part: kindOf(type), text: value }));
  // The space between the month and the day belongs to "Oct 14".
  pieces.forEach((piece, index) => {
    if (piece.part === 'separator' && pieces[index - 1]?.part === 'monthDay' && pieces[index + 1]?.part === 'monthDay') {
      piece.part = 'monthDay';
    }
  });
  return pieces.reduce((merged, piece) => {
    const last = merged[merged.length - 1];
    if (last && last.part === piece.part) last.text += piece.text;
    else merged.push({ ...piece });
    return merged;
  }, []);
}

/** "2026-11-19" -> {weekday: "Thu", day: "19", month: "Nov"}. Null for a missing or malformed date. */
export function formatDayParts(iso) {
  const parsed = parseDateOnly(iso);
  if (!parsed) return null;
  const time = utcTime(parsed);
  return { weekday: weekdayShortFormat.format(time), day: dayFormat.format(time), month: monthShortFormat.format(time) };
}

/** "2026-11-19" -> "Thursday, November 19, 2026". Empty string for a missing or malformed date. */
export function formatLongDate(iso) {
  const parsed = parseDateOnly(iso);
  return parsed ? longDateFormat.format(utcTime(parsed)) : '';
}

/**
 * The Monday-to-Sunday week that starts on a day number (days since 1970-01-01, see weeks.js):
 * "Nov 30 – Dec 6", or "Dec 7 – 13" inside one month.
 */
export function formatWeekRange(startDay) {
  return monthDayFormat.formatRange(startDay * DAY_MS, (startDay + 6) * DAY_MS);
}

/** 20 -> "20%", 12.5 -> "12.5%". Empty string when there is no weight. */
export function formatWeight(weight) {
  if (typeof weight !== 'number' || !Number.isFinite(weight)) return '';
  return percentFormat.format(weight / 100);
}

/** 1400 -> "1,400". */
export function formatCount(n) {
  return countFormat.format(n);
}

/** plural(1, "date", "dates") -> "date"; plural(14, "date", "dates") -> "dates". */
export function plural(n, one, other) {
  return pluralRules.select(n) === 'one' ? one : other;
}

/** "exam" -> "Exam". Anything unknown reads as "Other". */
export function typeLabel(type) {
  return TYPE_LABELS.get(type) ?? 'Other';
}

/**
 * Seconds until a limit resets, as words that follow "Try again":
 * "in a minute", "in about 20 minutes", "in about an hour", "in about 5 hours", or "later".
 */
export function formatRetryAfter(seconds) {
  const total = Number(seconds);
  if (seconds === null || seconds === undefined || !Number.isFinite(total) || total <= 0) return 'later';
  if (total < 90) return 'in a minute';
  const minutes = Math.round(total / 60);
  if (minutes < 60) return `in about ${formatCount(minutes)} minutes`;
  const hours = Math.round(total / 3600);
  return hours <= 1 ? 'in about an hour' : `in about ${formatCount(hours)} hours`;
}

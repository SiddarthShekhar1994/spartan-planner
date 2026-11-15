/**
 * Class colors. Each class keeps the same color everywhere because colors follow the
 * order the classes were added (ascending syllabus id). A color is always shown next to
 * the class name, never on its own.
 */

export const CLASS_COLORS = Object.freeze(['#7AA2FF', '#FF8FB1', '#6EE7B7']);

/** 0 -> blue, 1 -> pink, 2 -> green, 3 -> blue again. */
export function colorForIndex(index) {
  const count = CLASS_COLORS.length;
  const whole = Math.trunc(Number(index));
  const position = Number.isFinite(whole) ? ((whole % count) + count) % count : 0;
  return CLASS_COLORS[position];
}

/** Map of syllabus id -> color, assigned by ascending id. */
export function classColorMap(syllabi) {
  const ids = [...new Set((syllabi ?? []).map((syllabus) => syllabus.id))].sort((a, b) => a - b);
  return new Map(ids.map((id, index) => [id, colorForIndex(index)]));
}

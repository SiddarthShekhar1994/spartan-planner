/**
 * Finding the date words inside a source sentence, so they can be highlighted.
 * Pure function: no DOM.
 */

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * splitAround("Quiz 6 is on Thursday, November 19, in class.", "Thursday, November 19")
 *   -> {before: "Quiz 6 is on ", match: "Thursday, November 19", after: ", in class."}
 *
 * The phrase is matched as written first. PDF text wraps mid-sentence, so if that fails the
 * phrase is matched again with any run of spaces or line breaks counting as one space, and
 * without regard to capitals. When the phrase is missing, empty, or not in the sentence, the
 * whole sentence comes back in `before` and `match` is empty.
 */
export function splitAround(sentence, phrase) {
  const text = typeof sentence === 'string' ? sentence : '';
  const wanted = typeof phrase === 'string' ? phrase.trim() : '';
  if (!text || !wanted) return { before: text, match: '', after: '' };

  let start = text.indexOf(wanted);
  let length = wanted.length;
  if (start === -1) {
    const pattern = new RegExp(wanted.split(/\s+/).map(escapeRegExp).join('\\s+'), 'i');
    const found = pattern.exec(text);
    if (!found) return { before: text, match: '', after: '' };
    start = found.index;
    length = found[0].length;
  }
  return { before: text.slice(0, start), match: text.slice(start, start + length), after: text.slice(start + length) };
}

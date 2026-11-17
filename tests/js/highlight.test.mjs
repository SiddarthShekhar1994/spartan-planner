import assert from 'node:assert/strict';
import { test } from 'node:test';

import { splitAround } from '../../frontend/js/highlight.js';

test('the date words are cut out of the sentence', () => {
  assert.deepEqual(splitAround('Quiz 6 is on Thursday, November 19, in class.', 'Thursday, November 19'), {
    before: 'Quiz 6 is on ', match: 'Thursday, November 19', after: ', in class.',
  });
});

test('the three parts always join back into the sentence', () => {
  const sentence = 'The midterm is on Wednesday,\n   October 14, in class.';
  const { before, match, after } = splitAround(sentence, 'Wednesday, October 14');
  assert.equal(before + match + after, sentence);
  assert.equal(match, 'Wednesday,\n   October 14');
});

test('capitals do not matter when the exact phrase is not there', () => {
  assert.equal(splitAround('Lab report 5: due date TBA.', 'due date tba').match, 'due date TBA');
});

test('the first place the phrase appears is the one marked', () => {
  const { before, after } = splitAround('Dec 7 and again Dec 7.', 'Dec 7');
  assert.equal(before, '');
  assert.equal(after, ' and again Dec 7.');
});

test('characters that mean something in a pattern are matched as written', () => {
  assert.equal(splitAround('Due 12/7 (Mon.) at 5 p.m. [sharp]', '(mon.)').match, '(Mon.)');
  assert.equal(splitAround('Worth $5 * 2', '$5  *  2').match, '$5 * 2');
});

test('nothing is marked when there is no phrase or it is not in the sentence', () => {
  for (const phrase of [null, undefined, '', '   ', 'Friday, November 20', 42]) {
    assert.deepEqual(splitAround('Homework 7 is due Monday.', phrase), { before: 'Homework 7 is due Monday.', match: '', after: '' });
  }
  assert.deepEqual(splitAround(null, 'Monday'), { before: '', match: '', after: '' });
});

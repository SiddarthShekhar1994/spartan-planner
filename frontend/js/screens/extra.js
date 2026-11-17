/**
 * Setup question 2 of 2: extended time. Four big choices: No, 1.5x, 2x, or your own number.
 * It asks only for a number and says no reason is needed.
 *
 * PRIVACY: the answer is saved in this browser only (see settings.js). It is never sent to
 * the server, in any form.
 */
import { el, icon } from '../icons.js';
import { cleanMultiplier, MAX_MULTIPLIER, MIN_MULTIPLIER, PRESET_MULTIPLIERS, readSettings, saveMultiplier } from '../settings.js';

const CUSTOM = 'custom';
const OPTIONS = [
  { value: '1', label: 'No', detail: 'regular time' },
  { value: '1.5', label: '1.5x', detail: 'time and a half' },
  { value: '2', label: '2x', detail: 'double time' },
  { value: CUSTOM, label: 'Other', detail: 'your own number' },
];
const ERROR = `Use a number from ${MIN_MULTIPLIER} to ${MAX_MULTIPLIER}, like 1.25.`;

export function render(container) {
  const saved = readSettings().multiplier;
  const isPreset = PRESET_MULTIPLIERS.includes(saved);
  let choice = isPreset ? String(saved) : CUSTOM;

  const customInput = el('input', {
    id: 'custom', type: 'number', inputmode: 'decimal', min: String(MIN_MULTIPLIER), max: String(MAX_MULTIPLIER), step: '0.05',
    value: isPreset ? '1.25' : String(saved), 'aria-describedby': 'extra-err',
  });
  const error = el('p', { class: 'field-err', id: 'extra-err', hidden: true }, icon('alert'), el('span', {}, ERROR));
  const customRow = el('div', { class: 'cust', hidden: choice !== CUSTOM },
    el('label', { class: 'cust-label', for: 'custom' }, 'Your number'), customInput, el('span', {}, 'times regular time'));

  const clearError = () => {
    error.hidden = true;
    customInput.removeAttribute('aria-invalid');
  };
  customInput.addEventListener('input', () => {
    clearError();
    saveMultiplier(customInput.value); // only a valid number is saved
  });

  const option = ({ value, label, detail }) => {
    const id = `m-${value.replace('.', '-')}`;
    const input = el('input', { type: 'radio', name: 'mult', id, value, checked: choice === value });
    input.addEventListener('change', () => {
      choice = value;
      customRow.hidden = choice !== CUSTOM;
      clearError();
      if (choice === CUSTOM) {
        saveMultiplier(customInput.value);
        customInput.focus();
        customInput.select();
      } else saveMultiplier(value);
    });
    return el('div', { class: 'opt' }, input,
      el('label', { for: id }, el('span', { class: 'opt-n' }, label), el('span', { class: 'opt-w' }, detail)));
  };

  /** Don't leave with a number that isn't 1 to 4: show the error next to the field instead. */
  const onNext = (event) => {
    const value = choice === CUSTOM ? customInput.value : choice;
    if (cleanMultiplier(value) !== null) {
      saveMultiplier(value);
      return;
    }
    event.preventDefault();
    error.hidden = false;
    customInput.setAttribute('aria-invalid', 'true');
    customInput.focus();
  };

  container.append(el('div', { class: 'screen col' },
    el('h1', { tabindex: '-1' }, 'Real talk: do you get extended time?'),
    el('p', { class: 'lead' }, "You don't need to tell me why."),
    el('fieldset', { class: 'opts-set' }, el('legend', { class: 'visually-hidden' }, 'Extended time'),
      el('div', { class: 'opts' }, OPTIONS.map(option))),
    customRow, error,
    el('p', { class: 'note' }, 'Stays on your device. It never leaves it.'),
    el('div', { class: 'actions' },
      el('a', { class: 'btn btn-primary', href: '#/dates', onclick: onNext }, 'See my dates'),
      el('a', { class: 'btn btn-link', href: '#/hours' }, 'Back'))));
}

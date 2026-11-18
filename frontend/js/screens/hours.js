/**
 * Setup question 1 of 2: free study hours per week. One big number and a slider.
 * The answer is saved in this browser only (see settings.js). It is never sent anywhere.
 */
import { formatCount } from '../format.js';
import { el } from '../icons.js';
import { MAX_HOURS, MIN_HOURS, perDayText, readSettings, saveHours } from '../settings.js';
import { speaker } from '../speaker.js';

export function render(container) {
  const { hours } = readSettings();
  const number = el('span', { class: 'bignum', id: 'hours-num' }, formatCount(hours));
  const help = el('p', { class: 'muted setup-help', id: 'hours-help' }, `About ${perDayText(hours)} a day.`);
  const slider = el('input', {
    id: 'hours', class: 'slider', type: 'range', min: String(MIN_HOURS), max: String(MAX_HOURS), step: '1',
    value: String(hours), 'aria-describedby': 'hours-help',
  });
  slider.addEventListener('input', () => {
    const value = Number(slider.value);
    number.textContent = formatCount(value);
    help.textContent = `About ${perDayText(value)} a day.`;
    saveHours(value);
  });

  container.append(el('div', { class: 'screen col' },
    speaker(el('h1', { tabindex: '-1' }, 'How many hours a week can you study?'),
      el('p', { class: 'lead' }, 'A rough guess is fine.')).root,
    el('div', { class: 'card setup-card' },
      el('p', {}, number),
      el('p', { class: 'setup-unit' }, 'hours a week'),
      el('label', { class: 'visually-hidden', for: 'hours' }, 'Free study hours per week'),
      slider,
      el('div', { class: 'scale', 'aria-hidden': 'true' },
        el('span', {}, formatCount(MIN_HOURS)), el('span', {}, formatCount(MAX_HOURS / 2)), el('span', {}, formatCount(MAX_HOURS))),
      help),
    el('p', { class: 'note' }, 'Stays on your device.'),
    el('div', { class: 'actions' },
      el('a', { class: 'btn btn-primary', href: '#/extra', onclick: () => saveHours(slider.value) }, 'Next'),
      el('a', { class: 'btn btn-link', href: '#/' }, 'Back'))));
}

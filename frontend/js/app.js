/**
 * App shell: startup plus a small hash router.
 * #/ (or an empty or unknown hash) shows the upload screen; #/dates shows the dates screen.
 * Each screen module exports render(container) and may return a cleanup function.
 * Because every screen is a hash, the browser's Back button steps back through the flow.
 */
import { getClientId } from './client-id.js';
import { el } from './icons.js';
import * as datesScreen from './screens/dates.js';
import * as extraScreen from './screens/extra.js';
import * as hoursScreen from './screens/hours.js';
import * as planScreen from './screens/plan.js';
import * as uploadScreen from './screens/upload.js';
import { clearToast } from './toast.js';

const HOME = '#/';
const SETUP_STEPS = 3;
// `step` is the screen's place in setup (upload, hours, extended time). The header shows it as dots.
// `link` is a text link in the header, to hop between the dates and the plan.
const ROUTES = new Map([
  [HOME, { screen: uploadScreen, title: 'Upload syllabi · Spartan Planner', step: 1 }],
  ['#/hours', { screen: hoursScreen, title: 'Study hours · Spartan Planner', step: 2 }],
  ['#/extra', { screen: extraScreen, title: 'Extended time · Spartan Planner', step: 3 }],
  ['#/dates', { screen: datesScreen, title: 'Your dates · Spartan Planner', link: { href: '#/plan', label: 'My plan' } }],
  ['#/plan', { screen: planScreen, title: 'Your plan · Spartan Planner', link: { href: '#/dates', label: 'My dates' } }],
]);

const main = document.getElementById('main');
const headerSlot = document.getElementById('header-slot');
let currentRoute = null;
let cleanup = null;

function show() {
  const hash = window.location.hash;
  // In-page anchors such as #main are not routes. Only the first render maps them to home.
  if (currentRoute !== null && hash !== '' && !hash.startsWith('#/')) return;
  const routeKey = ROUTES.has(hash) ? hash : HOME;
  if (routeKey === currentRoute) return;

  const isFirstRender = currentRoute === null;
  const route = ROUTES.get(routeKey);
  runCleanup();
  clearToast(); // an Undo from the last screen has nothing to act on here
  main.replaceChildren();
  currentRoute = routeKey;
  document.title = route.title;
  headerSlot?.replaceChildren(...[
    route.step ? progressDots(route.step) : null,
    route.link ? el('a', { class: 'navlink', href: route.link.href }, route.link.label) : null,
  ].filter(Boolean));
  try {
    const result = route.screen.render(main);
    cleanup = typeof result === 'function' ? result : null;
  } catch (error) {
    console.error(error);
    main.replaceChildren(crashView());
  }

  if (!isFirstRender) {
    window.scrollTo(0, 0);
    main.querySelector('h1')?.focus();
  }
}

/** "Step 2 of 3" for screen readers, three dots for the eye: done, now (the wide one), still to come. */
function progressDots(step) {
  const dots = Array.from({ length: SETUP_STEPS }, (_, index) => {
    const place = index + 1;
    return el('span', { class: place < step ? 'is-done' : place === step ? 'is-now' : '' });
  });
  return el('div', { class: 'dots', role: 'img', 'aria-label': `Step ${step} of ${SETUP_STEPS}` }, dots);
}

function runCleanup() {
  const previous = cleanup;
  cleanup = null;
  if (!previous) return;
  try {
    previous();
  } catch (error) {
    console.error(error);
  }
}

/** Shown only if a screen fails to draw, so the page is never left blank. */
function crashView() {
  return el('div', { class: 'screen col' },
    el('h1', { tabindex: '-1' }, 'Something broke on my end.'),
    el('p', { class: 'lead' }, 'Reload the page and try again.'),
    el('div', { class: 'actions' },
      el('button', { type: 'button', class: 'btn btn-primary', onclick: () => window.location.reload() }, 'Reload the page')));
}

function hasFiles(event) {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files');
}

function start() {
  getClientId(); // make sure this browser has its ID before the first request

  // The skip link must not change the hash, or the router would treat it as navigation.
  document.querySelector('.skip-link')?.addEventListener('click', (event) => {
    event.preventDefault();
    main.focus();
  });

  // A file dropped outside the drop box would make the browser leave the app to open it.
  window.addEventListener('dragover', (event) => {
    if (!hasFiles(event) || event.defaultPrevented) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'none';
  });
  window.addEventListener('drop', (event) => {
    if (hasFiles(event)) event.preventDefault();
  });

  window.addEventListener('hashchange', show);
  show();
}

start();

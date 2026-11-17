/**
 * App shell: startup plus a small hash router.
 * #/ (or an empty or unknown hash) shows the upload screen; #/dates shows the dates screen.
 * Each screen module exports render(container) and may return a cleanup function.
 * Because every screen is a hash, the browser's Back button steps back through the flow.
 */
import { getClientId } from './client-id.js';
import { el } from './icons.js';
import * as datesScreen from './screens/dates.js';
import * as uploadScreen from './screens/upload.js';
import { clearToast } from './toast.js';

const HOME = '#/';
const ROUTES = new Map([
  [HOME, { screen: uploadScreen, title: 'Upload syllabi · Spartan Planner' }],
  ['#/dates', { screen: datesScreen, title: 'Your dates · Spartan Planner' }],
]);

const main = document.getElementById('main');
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

/**
 * The planner's face: a little card-file folder that says each screen's headline in a
 * speech bubble. It is decoration (hidden from screen readers); the words in the bubble are
 * the real heading and lead, so nothing is lost without it.
 *
 * Moods change its face, never its place: "hi" (default), "reading" (eyes down, while a file
 * is read or dates load), "happy" (something was found) and "worried" (something went wrong).
 */
import { el } from './icons.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const MOODS = new Set(['hi', 'reading', 'happy', 'worried']);

function svg(tag, attributes = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  node.append(...children);
  return node;
}

const eye = (cx, cy, ry) => svg('ellipse', { cx, cy, rx: '3.5', ry });
const line = (d) => svg('path', { d, class: 'av-line' });

function face() {
  return svg('svg', { viewBox: '0 0 64 64', class: 'avatar', 'aria-hidden': 'true', focusable: 'false', 'data-mood': 'hi' },
    // A folder: the tab, the body, and a highlighter label on the tab.
    svg('rect', { class: 'av-body', x: '4', y: '6', width: '28', height: '22', rx: '8' }),
    svg('rect', { class: 'av-body', x: '4', y: '16', width: '56', height: '42', rx: '12' }),
    svg('rect', { class: 'av-mark', x: '10', y: '10.5', width: '16', height: '5', rx: '2.5' }),
    svg('g', { class: 'av-mood av-hi' },
      svg('g', { class: 'av-open' }, eye('24', '35', '4.5'), eye('40', '35', '4.5')), line('M27 45q5 4 10 0')),
    svg('g', { class: 'av-mood av-reading' },
      svg('g', { class: 'av-glance' }, eye('24', '38', '3.5'), eye('40', '38', '3.5')), line('M29 47h6')),
    svg('g', { class: 'av-mood av-happy' }, line('M19.5 36.5q4.5-6 9 0'), line('M35.5 36.5q4.5-6 9 0'), line('M25 43q7 8 14 0')),
    svg('g', { class: 'av-mood av-worried' }, eye('24', '35', '4.5'), eye('40', '35', '4.5'), line('M27 47q5-3 10 0')));
}

/**
 * speaker(headingNode, leadNode) -> {root, setMood}
 * `root` holds the avatar and a bubble with the heading and the lead inside it.
 */
export function speaker(heading, lead = null) {
  const avatar = face();
  const root = el('div', { class: 'say' }, avatar, el('div', { class: 'bubble' }, heading, lead));
  const setMood = (mood) => {
    const next = MOODS.has(mood) ? mood : 'hi';
    if (avatar.getAttribute('data-mood') !== next) avatar.setAttribute('data-mood', next);
  };
  return { root, setMood };
}

/**
 * Safe DOM builders: el() for HTML elements, icon() for inline SVG icons, and
 * dotted() for "Exam · 20%" style lists.
 *
 * Everything is built with createElement / createElementNS and text nodes, never
 * innerHTML, so text from the server or the student can't turn into markup.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';

/** 24x24 stroke icons: [tag, attributes] pairs drawn in currentColor. */
const ICONS = {
  upload: [
    ['path', { d: 'M12 15V4' }],
    ['path', { d: 'M7.5 8.5 12 4l4.5 4.5' }],
    ['path', { d: 'M4 14.5V18a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3.5' }],
  ],
  check: [
    ['circle', { cx: '12', cy: '12', r: '9' }],
    ['path', { d: 'm8.5 12.5 2.5 2.5 4.5-5' }],
  ],
  clock: [
    ['circle', { cx: '12', cy: '12', r: '9' }],
    ['path', { d: 'M12 7.5V12l3 2' }],
  ],
  spinner: [
    ['circle', { cx: '12', cy: '12', r: '9', opacity: '0.3' }],
    ['path', { d: 'M21 12a9 9 0 0 0-9-9' }],
  ],
  alert: [
    ['path', { d: 'M12 3.5 2.5 20h19L12 3.5Z' }],
    ['path', { d: 'M12 10v4' }],
    ['path', { d: 'M12 17h.01' }],
  ],
  info: [
    ['circle', { cx: '12', cy: '12', r: '9' }],
    ['path', { d: 'M12 16v-4.5' }],
    ['path', { d: 'M12 8h.01' }],
  ],
  question: [
    ['circle', { cx: '12', cy: '12', r: '9' }],
    ['path', { d: 'M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.25-1 .8-1 1.45v.5' }],
    ['path', { d: 'M12 17h.01' }],
  ],
  calendar: [
    ['rect', { x: '3.5', y: '5', width: '17', height: '15.5', rx: '2.5' }],
    ['path', { d: 'M3.5 10h17' }],
    ['path', { d: 'M8 3v4' }],
    ['path', { d: 'M16 3v4' }],
  ],
  chevron: [['path', { d: 'm9 6 6 6-6 6' }]],
  'arrow-right': [
    ['path', { d: 'M5 12h14' }],
    ['path', { d: 'm13 6 6 6-6 6' }],
  ],
  plus: [
    ['path', { d: 'M12 5v14' }],
    ['path', { d: 'M5 12h14' }],
  ],
};

/**
 * el("button", {type: "button", class: "button", onclick: fn}, "Save")
 * - class sets className, value sets the live value, style is an object of CSS properties
 * - on* keys with a function become event listeners
 * - true adds an empty attribute; null, undefined and false skip the attribute
 * - children can be nodes, strings (added as text), arrays, or null to skip
 */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'value') node.value = value;
    else if (key === 'style') {
      for (const [property, setting] of Object.entries(value)) node.style.setProperty(property, setting);
    } else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  node.append(...children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false));
  return node;
}

/** An inline SVG icon, hidden from screen readers. Pair it with visible text. */
export function icon(name, className = '') {
  const svg = document.createElementNS(SVG_NS, 'svg');
  const attributes = {
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    'stroke-width': '2',
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    'aria-hidden': 'true',
    focusable: 'false',
    class: `icon icon-${name}${className ? ` ${className}` : ''}`,
  };
  for (const [key, value] of Object.entries(attributes)) svg.setAttribute(key, value);
  for (const [tag, shapeAttributes] of ICONS[name] ?? []) {
    const shape = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(shapeAttributes)) shape.setAttribute(key, value);
    svg.append(shape);
  }
  return svg;
}

/**
 * ["14 dates found", "2 need a date"] -> nodes that show "14 dates found · 2 need a date".
 * Screen readers hear a comma instead of the dot.
 */
export function dotted(parts) {
  const nodes = [];
  parts
    .filter((part) => typeof part === 'string' && part !== '')
    .forEach((part, index) => {
      if (index > 0) {
        nodes.push(el('span', { class: 'dot-sep', 'aria-hidden': 'true' }, ' · '));
        nodes.push(el('span', { class: 'visually-hidden' }, ', '));
      }
      nodes.push(document.createTextNode(part));
    });
  return nodes;
}

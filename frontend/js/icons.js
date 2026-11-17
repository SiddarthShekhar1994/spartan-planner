/**
 * Safe DOM builders: el() for HTML elements and icon() for the three inline SVG icons.
 *
 * Everything is built with createElement / createElementNS and text nodes, never
 * innerHTML, so text from the server or the student can't turn into markup.
 *
 * Icons appear only where they carry meaning: a check (read), a warning triangle
 * (needs your eyes) and the arrow that opens a row. Buttons and notes are text only.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';

/** 24x24 stroke icons: path data drawn in currentColor. */
const ICONS = {
  check: ['M5 12.5l4.5 4.5L19 7.5'],
  alert: ['M12 4L2.5 20h19L12 4z', 'M12 10v4.5', 'M12 17.5v.01'],
  chevron: ['M9 6l6 6-6 6'],
};

/**
 * el("button", {type: "button", class: "btn", onclick: fn}, "Save")
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

/** An inline SVG icon, hidden from screen readers. Always pair it with visible text. */
export function icon(name, className = '') {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.setAttribute('class', `ic ic-${name}${className ? ` ${className}` : ''}`);
  for (const d of ICONS[name] ?? []) {
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}

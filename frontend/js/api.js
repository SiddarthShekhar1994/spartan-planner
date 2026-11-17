/**
 * The only module that talks to the server. Every request carries the browser's
 * random X-Client-Id. Failures come back as ApiError with a message that is safe to
 * show the student as-is.
 */
import { getClientId } from './client-id.js';

const MESSAGES = {
  network: "I can't reach the server. Check your connection and try again.",
  tooLarge: 'That file is over 10 MB. Try a smaller copy, or paste the text instead.',
  tooMany: 'Too many uploads right now. Try again later.',
  server: 'Something broke on my end. Try again in a minute.',
  other: 'Something went wrong. Try again.',
};

export class ApiError extends Error {
  /**
   * @param {{status: number, code: string, message: string, retryAfterSeconds?: number|null}} details
   *   status is 0 when the server couldn't be reached at all.
   */
  constructor({ status, code, message, retryAfterSeconds = null }) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/** A message that is safe to show for any failure: the server's own words, or a friendly fallback. */
export function messageFor(error) {
  if (error instanceof ApiError) return error.message;
  console.error(error); // a bug in the page, not an answer from the server
  return MESSAGES.other;
}

/**
 * Send one request and return the parsed JSON body.
 * Pass `json` for a JSON body or `formData` for a multipart upload.
 */
export async function request(method, path, { json, formData } = {}) {
  const headers = { 'X-Client-Id': getClientId(), Accept: 'application/json' };
  let body;
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(json);
  } else if (formData !== undefined) {
    body = formData; // the browser sets the multipart boundary itself
  }

  let response;
  try {
    response = await fetch(path, { method, headers, body, cache: 'no-store', credentials: 'same-origin' });
  } catch {
    throw new ApiError({ status: 0, code: 'network', message: MESSAGES.network });
  }

  const data = await readJson(response);
  if (!response.ok) throw errorFromResponse(response, data);
  if (data === null || typeof data !== 'object') throw malformed(response.status);
  return data;
}

/** POST a PDF or .docx. Resolves to {syllabus, items}. */
export async function uploadSyllabusFile(file) {
  const formData = new FormData();
  formData.append('file', file, file.name);
  return expectUpload(await request('POST', '/api/syllabi', { formData }));
}

/** POST pasted syllabus text. Resolves to {syllabus, items}. */
export async function uploadSyllabusText(text) {
  const formData = new FormData();
  formData.append('text', text);
  return expectUpload(await request('POST', '/api/syllabi', { formData }));
}

/** This browser's classes, oldest first. Resolves to an array of syllabi. */
export async function listSyllabi() {
  return expectArray(await request('GET', '/api/syllabi'), 'syllabi');
}

/** Rename a class. Resolves to the updated syllabus. */
export async function renameSyllabus(id, className) {
  const data = await request('PATCH', `/api/syllabi/${encodeURIComponent(id)}`, { json: { class_name: className } });
  if (!isObject(data.syllabus)) throw malformed(200);
  return data.syllabus;
}

/** Every item for this browser: dated items first by date, then the ones that need a date. */
export async function listItems() {
  return expectArray(await request('GET', '/api/items'), 'items');
}

/**
 * Set, change or clear one item's date. `dueDate` is "YYYY-MM-DD" or null; `notSure` (only with
 * null) marks it "Not sure yet". Sending the same thing twice is safe. Resolves to the saved item.
 */
export async function saveItemDate(id, { dueDate, notSure = false }) {
  const data = await request('PATCH', `/api/items/${encodeURIComponent(id)}`, {
    json: { due_date: dueDate, not_sure: notSure },
  });
  if (!isObject(data.item)) throw malformed(200);
  return data.item;
}

async function readJson(response) {
  try {
    const text = await response.text();
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}

function errorFromResponse(response, data) {
  const { status } = response;
  const envelope = isObject(data) && isObject(data.error) ? data.error : null;
  const retryAfterSeconds =
    toSeconds(envelope ? envelope.retry_after_seconds : null) ?? parseRetryAfter(response.headers.get('Retry-After'));
  if (envelope && typeof envelope.message === 'string' && envelope.message.trim()) {
    const code = typeof envelope.code === 'string' ? envelope.code : 'error';
    return new ApiError({ status, code, message: envelope.message, retryAfterSeconds });
  }
  return new ApiError({ status, code: `http_${status}`, message: fallbackMessage(status), retryAfterSeconds });
}

function fallbackMessage(status) {
  if (status === 413) return MESSAGES.tooLarge;
  if (status === 429) return MESSAGES.tooMany;
  if (status >= 500) return MESSAGES.server;
  return MESSAGES.other;
}

function toSeconds(value) {
  if (value === null || value === undefined || value === '') return null;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? Math.ceil(seconds) : null;
}

/** Retry-After is either a number of seconds or an HTTP date. */
function parseRetryAfter(header) {
  if (!header) return null;
  const seconds = toSeconds(header.trim());
  if (seconds !== null) return seconds;
  const when = Date.parse(header);
  return Number.isNaN(when) ? null : Math.max(1, Math.ceil((when - Date.now()) / 1000));
}

function expectUpload(data) {
  if (!isObject(data.syllabus) || !Array.isArray(data.items)) throw malformed(200);
  return data;
}

function expectArray(data, key) {
  if (!Array.isArray(data[key])) throw malformed(200);
  return data[key];
}

function malformed(status) {
  return new ApiError({ status, code: 'bad_response', message: MESSAGES.other });
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

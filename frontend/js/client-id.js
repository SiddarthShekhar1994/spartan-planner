/**
 * The browser's random ID. There are no accounts: every row on the server is keyed
 * by this ID, sent as the X-Client-Id header. It never holds a name or an email.
 *
 * Stored in localStorage under "spartan.clientId". If storage is blocked (some private
 * windows), an in-memory ID is used for the rest of the visit.
 */

export const CLIENT_ID_STORAGE_KEY = 'spartan.clientId';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

let memoryId = null;

/** The ID to send with every request. Creates and saves one on the first visit. */
export function getClientId() {
  const stored = readStored();
  if (stored !== null && UUID_PATTERN.test(stored)) {
    memoryId = stored.toLowerCase();
    return memoryId;
  }
  // Nothing stored, a malformed value, or no storage at all: make one ID and keep it.
  if (memoryId === null) memoryId = newUuid();
  writeStored(memoryId);
  return memoryId;
}

function readStored() {
  try {
    return window.localStorage.getItem(CLIENT_ID_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(value) {
  try {
    window.localStorage.setItem(CLIENT_ID_STORAGE_KEY, value);
  } catch {
    // Storage is blocked or full. The in-memory ID still works for this visit.
  }
}

/** A random version 4 UUID. randomUUID needs a secure context, so plain http on a LAN falls back. */
function newUuid() {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi.randomUUID === 'function') {
    try {
      return cryptoApi.randomUUID();
    } catch {
      // Not allowed in this context. Fall through to getRandomValues.
    }
  }
  const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC 4122 variant
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

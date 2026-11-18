/**
 * The privacy note's one moving part: it shows this browser's random ID, so a tester can ask
 * for their data to be deleted. The ID is read from this browser; nothing is sent anywhere.
 */
import { getClientId } from './client-id.js';

const slot = document.getElementById('client-id');
if (slot) slot.textContent = getClientId();

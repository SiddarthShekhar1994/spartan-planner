# Changelog

## Avatar and more motion (2026-11-17)

Sid asked for an avatar that says the app's lines, and for at least 10 animations.

- **Avatar:** a small card-file folder with a face. It says each screen's headline and lead in a speech bubble, on all four screens. Its face changes with what is happening: reading (eyes down) while a file is read or dates load, happy when dates are found, worried when something fails. It is decoration for the eye; screen readers get the heading as before.
- **Motion,** 17 in all, each played once for one reason: the avatar settles in; its bubble rises in; it blinks once; its face changes softly; its eyes run along a line while it reads; a new file row rises in; the check settles in when a file is read; "Found N dates" rises in; buttons press in under a click; the drop box lifts while a file is held over it; the progress dot stretches into place; the highlighter sweeps across the extended-time choice you pick; "Your number" rises in; an opened row's sentence rises in; a date you just added or changed is marked once and the mark fades; a toast rises in; the dates rise in together when they load. The screen fade, the highlighter pass over a file and the row arrow were already there.
- All of it is in `frontend/css/motion.css`, uses transform and opacity only, and is off for anyone whose device asks for reduced motion.

**The brief changed with it.** `CLAUDE.md` used to say "Motion is rare and calm: one soft fade when the screen changes, and chart bars that grow once." Sid approved new wording on 2026-11-17: motion is plentiful but calm, each animation plays once for a reason, and the avatar is part of the look. Kept from the old rule: nothing bounces, bursts, staggers, counts up or repeats on its own.

## Setup questions (2026-11-17)

The two setup questions from the approved demo, one per screen, between upload and the dates.

- "How many hours a week can you study?": one big number and a slider from 1 to 40, with "About 1 hr 45 min a day." under it. Starts at 12.
- "Real talk: do you get extended time?": four big choices (No, 1.5x, 2x, Other). Other takes a number from 1 to 4. It says "You don't need to tell me why." and asks for nothing else.
- Progress dots in the header through setup: upload, hours, extended time.
- The upload panel's button is now "Next" and leads to the hours question. "See my dates" is on the extended-time screen.
- Both answers are saved in the browser's localStorage only (`frontend/js/settings.js`). Nothing reads them yet: the plan screen that uses them is the next stage.
- Tests: `tests/js/settings.test.mjs` checks the values, and checks that the module that talks to the server never touches these answers and that the server code has no word for them.

Different from the old Build 2 prompt, following the demo: a slider instead of a number box with quick picks, no live example under the choices, and no Skip (regular time is already picked).

## Card-file look and automatic dates, stage one (2026-11-17)

The upload screen and the dates screen now look and work like the demo Sid approved. Dates go in on their own. Nothing is confirmed one by one.

### What changed

- New look: a warm off-white page by default, a dark theme that follows the device, Lexend headings, Atkinson Hyperlegible body, one spacing scale, solid hover swaps, and three icons only (check, warning, arrow).
- Upload screen: the drop box under a "New class" tab, one row per file (up next, reading, read, couldn't read), and a "Found N dates in N classes." panel with "See my dates". While a file is read, a little page gets one slow highlighter pass.
- "Got N dates." replaces the plain list: dates grouped by week, tap a row for the source sentence with the date words highlighted, "Change the date", a "Worth a look" flag when the sentence couldn't be found, and "You set this" on a date the student changed.
- An amber box asks only about dates the syllabus doesn't give: "I didn't guess. When is it actually due?", with Add and "Not sure yet".
- Toasts with Undo for adding a date, changing a date, "Not sure yet" and removing a file.
- `PATCH /api/items/{id}` saves a date, clears it, or marks the item "Not sure yet". Migration 002 adds `extracted_due_date`, which keeps what the syllabus said and is never overwritten. Item `status` is now `unchecked` (as extracted), `edited` (the student's date differs) or `skipped` ("Not sure yet").
- Tests: 746 offline tests, up from 697. New ones cover the date endpoint and the migration, plus browser-side unit tests for week grouping, highlighting and formatting, run with Node's built-in test runner.

### Sid's decisions (2026-11-17)

- Dates that have already passed go in one closed "Already passed" group at the bottom.
- "Paste text instead" and Rename stay, as plain text links.
- Date changes are saved on the server, not only in the browser.

### Added during the build, not yet approved by Sid

- The server refuses a date outside the years 2000 to 2100, to catch a mistyped year.
- Items marked "Not sure yet" sit in a closed "Not sure yet" group so a date can still be added later. In the demo they disappeared.
- A class chip shows the course code ("CS 146") when the class name starts with one, and the whole name otherwise.
- After 15 seconds of reading, the row adds "Still reading. Long ones can take a minute."

### Different from the demo, on purpose

- No date chips while a file is being read: the dates aren't known until Claude answers.
- The progress dots, "Build my plan" and the line "They're in your plan already." are left out until the setup questions and the plan screen exist.
- A row opens at once with a short fade. The demo animated its height, and the brief allows only transform and opacity.
- Dark mode follows the device. The demo's theme switch and "Start over" were demo tools.

### Known gaps

- Only the date can be edited so far, not the title, type or weight.
- A class that has been read can't be removed yet.
- After "Not sure yet", the upload screen's "N don't have a date yet. I'll ask you about those." still counts that item.
- A date is saved before the screen updates, rather than updating first and saving after.
- Uploads have no idempotency key yet, so "Try again" after a dropped connection can read the same syllabus twice.
- The server sends no cache header for frontend files, so a browser can keep an old copy after a change (Ctrl+F5).

## Build 1 (2026-11-15)

Upload a syllabus and see every deadline next to the exact sentence it came from.

### What was built

- FastAPI app that serves the frontend and the API from one place, with pinned requirements, `.env` in `.gitignore`, and `.env.example` listing `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` and `DATABASE_PATH`.
- SQLite database with numbered migrations: a `syllabi` table and an `items` table, keyed by the browser's random ID.
- `POST /api/syllabi` for a PDF, a Word .docx or pasted text (up to 10 MB), `GET /api/syllabi`, `PATCH /api/syllabi/{id}` to rename a class, and `GET /api/items`. Every error comes back in one shape with a short, friendly message.
- Text extraction with pypdf and python-docx (Word tables become one line per row). The uploaded file is closed, which deletes it, as soon as its text is read and before Claude is called.
- Extraction with Claude's structured output (`claude-haiku-5-5` by default), using prompt v1 in `backend/prompts.py`.
- Checks on Claude's answer before anything is saved: the quote must be in the syllabus (or the item is flagged), the date must match its date phrase (or the item needs a date), weights must be 0 to 100, and copies of the same deadline are dropped.
- Upload limits: 10 syllabi per browser per day and 50 uploads per network per day.
- Upload screen with a drop zone, a file picker, a paste box, a one-at-a-time queue, class colors and Rename, plus a plain list of dates with "Needs a date" badges, the source sentence, and a warning when a quote couldn't be matched.
- The browser's random ID in localStorage, sent as `X-Client-Id` on every request.
- 697 tests that run offline with a fake Claude, and one live test (`py -m pytest -m live`).

### Sid's decisions

- The class name is read from the syllabus, with a Rename button on each class.
- When a syllabus states no term, the year comes from the upload date.
- 50 uploads per IP address per day, kept in memory only: never saved, never logged, reset by a restart.
- A date is kept only when its date phrase names that day: the month and day must match, and a weekday, if given, must agree.
- Schema additions: `extraction_model` and `prompt_version` on each syllabus, and `date_text` (the exact date phrase) on each item.
- The project moved to `C:\Projects\spartan-planner`.
- Term check: when the syllabus states a term with a year ("Fall 2026"), a due date outside that term goes to "Needs a date" (`backend/services/terms.py`).
- "See my dates" stays hidden until every queued syllabus has been read, so the dates list is never half done.

### Added during the build, approved by Sid on 2026-11-15

- Three more date checks, each of which can only remove a date: a year in the date phrase must match; "Oct 14 or 16" and "Oct 14/16" give no date; "the week of" and "every" give no date.
- Word files that unpack to more than 50 MB are refused.

### Review fixes

- PDFs stop being read once their text passes 1,000,000 characters, so a tiny file whose pages all repeat one huge page gets "too long" at once instead of tying up the server.
- Word tables are read in one pass over the file, so a big table of vertically merged cells, or a cell that claims a huge width, takes a fraction of a second instead of minutes. The text is the same as before.
- A Word file's "Different First Page" header is read too, before the running header.
- The run command in `backend/main.py` now matches the README's and turns uvicorn's access log off, so IP addresses stay out of the logs.
- Repeats: an undated item is dropped only when its sentence is a copy of one already kept, so different deadlines that share a name ("Lab report" in Week 3 and Week 7, a weekly rule next to a dated first one) all stay. The sample's grading-table "Final exam 25%" now shows as its own undated item.
- Date checks also read the date words right next to Claude's date phrase in the quote, so a shortened phrase ("Dec 7" from "Dec 7–11", "October 14" from "Thursday, October 14") can't keep a date, and "Oct 1" no longer counts as inside "Oct 14".
- A list of days gives no date ("Oct 14, 16", "Dec 7, 9, or 11", "Oct 14 + 16", "Oct 14 (or 16 for Section 2)"). A year or a time after the comma is still one day.
- Excel's "19-Oct" and "19-Oct-2026" and dashed "10-14-2026" dates are read now. A bare "10-14" still needs a date.
- The field descriptions Claude sees in the reply schema moved from `backend/schemas.py` to `backend/prompts.py` as part of v1, word for word, so every prompt text lives in one file.
- The Claude call waits up to 600 seconds (the SDK's long-request default) instead of 120, so a long reply isn't cut off and then written again by each retry.

### Live test fixes

- Prompt v1 now asks for the full sentence even when it wraps onto the next line (PDF text wraps a lot). Before, Claude sometimes quoted only the first line of "…on Wednesday, / October 14, in class.", which cut the date out of the quote, so the date check rightly dropped it. Nothing real had been stored with v1, so v1 was edited in place. After the fix the live test passed 5 times out of 5 (3 on claude-sonnet-5-5, 2 on claude-haiku-5-5).
- When the live test misses a date, it now prints what Claude and the checks produced.

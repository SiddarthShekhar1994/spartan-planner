# Changelog

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

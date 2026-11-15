# Spartan Planner

Turns course syllabi into a semester plan. This is Build 1 of 5: upload a syllabus and see every deadline next to the exact sentence it came from.

## What Build 1 does

- **Upload.** Drop PDF or Word (.docx) files on the upload screen, pick them with "Choose files", or paste the text. Syllabi are read one at a time. Each class shows "Waiting in line…", then "Reading it now…", then a summary such as "12 dates found · 6 need a date · 1 quote to double-check". "See my dates" appears once every syllabus in line has been read, so the list is never half done.
- **Find the deadlines.** The server pulls the text out of the file and sends it to Claude (`claude-haiku-5-5` unless `.env` says otherwise), which lists every assignment, quiz, exam, essay, project and required reading with the sentence it came from.
- **Check Claude's answer.** Before anything is saved, the app checks each item itself: the quoted sentence must really be in the syllabus, the date must match the date phrase in that sentence and fall inside the term the syllabus states, and copies of the same deadline are dropped. Vague dates ("TBA", "last week of class", "Dec 7–11") are saved with no date and show as "Needs a date". It never guesses a date.
- **Class names.** Read from the syllabus (for example "CS 101: Introduction to Programming"). Every class has a Rename button.
- **Your dates.** "See my dates" lists every deadline, dated ones first by date, then the ones that need a date. Each card shows the class (with its color), the type and weight, the date, and the source sentence. If the sentence couldn't be found in the syllabus, the card says so.
- **No accounts.** The browser makes a random ID on the first visit and sends it with every request. Each browser sees only its own classes.

Not in Build 1: checking dates one card at a time, the study-hours and extended-time questions, the plan, and the calendar export. They come in builds 2 and 3.

The API, if you want to poke at it at http://127.0.0.1:8000/docs (every request needs an `X-Client-Id` header holding a UUID):

| Request | What it does |
| --- | --- |
| `POST /api/syllabi` | Upload one syllabus: form field `file` (PDF or .docx) or `text` (pasted). Returns the class and its items. |
| `GET /api/syllabi` | This browser's classes, oldest first. |
| `PATCH /api/syllabi/{id}` | Rename a class: JSON `{"class_name": "CS 101"}`. |
| `GET /api/items` | Every deadline for this browser. |

## Setup (once)

Open Windows PowerShell and go to the project folder:

```powershell
Set-Location C:\Projects\spartan-planner
```

1. Create the virtual environment with Python 3.13:

   ```powershell
   py -3.13 -m venv .venv
   ```

2. Let this window run the activation script:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```

   `-Scope Process` changes the policy for this one PowerShell window only. Nothing is saved, and it ends when you close the window. If PowerShell asks you to confirm, type `Y` and press Enter. You only need this step when step 3 says running scripts is disabled.

3. Activate the virtual environment. Do this in every new PowerShell window before you run anything else:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   The prompt now starts with `(.venv)`.

4. Check that `py` now runs the virtual environment's Python:

   ```powershell
   py -c "import sys; print(sys.prefix)"
   ```

   It should print `C:\Projects\spartan-planner\.venv`. Anything else means the venv isn't active (see Troubleshooting).

5. Install the pinned packages and pytest:

   ```powershell
   py -m pip install -r requirements-dev.txt
   ```

6. Make your settings file. First time only: if `.env` already exists, this replaces it, key and all.

   ```powershell
   Copy-Item .env.example .env
   ```

7. Add your Anthropic API key:

   ```powershell
   notepad .env
   ```

   Paste the key right after `ANTHROPIC_API_KEY=` (no quotes, no spaces), then save and close. `CLAUDE_MODEL` and `DATABASE_PATH` can stay as they are. `.env` is in `.gitignore`. Never put the key anywhere else.

## Run

With the venv active, from the project folder:

```powershell
py -m uvicorn backend.main:app --reload --reload-dir backend --no-access-log
```

Then open http://127.0.0.1:8000. Stop the server with Ctrl+C.

- **Why `--no-access-log`:** uvicorn's access log writes one line per request, and each line holds the visitor's IP address. The app's rule is that logs hold only event names, counts, status codes and timings, so the access log stays off. You still see the app's own lines, such as `extraction_finished items=12 ms=8450`.
- **Why `--reload-dir backend`:** `--reload` restarts the server when a Python file changes. Without `--reload-dir`, uvicorn checks every `.py` file under the project folder several times a second, including the thousands inside `.venv`. With it, only `backend\` is watched. Frontend files never need a restart, because the server reads them from disk on every request: just reload the page.
- `.env` is read once, when the server starts. After you edit it, press Ctrl+C and start the server again.

To try it: drop one of your syllabi on the upload screen, wait for the summary line, then click "See my dates". Vague dates show under "Needs a date".

## Tests

```powershell
py -m pytest
```

Runs all 664 regular tests in about 15 seconds. They run offline with a fake Claude, and a guard makes any test that tries to reach the real API fail.

```powershell
py -m pytest -m live
```

Sends `tests\fixtures\sample_syllabus.txt` to the real Claude API once, using the key and model in `.env`, and checks the answer loosely: the class name has "CS 101", Quiz 1, the midterm and the final have the right dates, the TBA lab report, the last-week presentations and the every-Friday readings have none, and at least 80% of the quotes are found in the syllabus. It costs a fraction of a cent. Without a key it skips itself.

## Where things live

- **Database:** `data\spartan.db` (SQLite), created the first time the server starts. Two tables: `syllabi` (class name, the file's own name, the model and prompt version that read it, when) and `items` (title, type, date, date phrase, weight, source sentence, two flags, status). Rows are keyed by the browser's random ID. The `data` folder is gitignored. Set `DATABASE_PATH` in `.env` to put the file somewhere else.
- **Uploaded files never stay on disk.** Starlette keeps an upload of up to 1 MB in memory and spools anything bigger to a temporary file in `%TEMP%`. The app closes the upload right after reading its text, and closing deletes that temporary file. This happens before Claude is called, and on every error path too. Only the extracted items and their source sentences are saved: never the file, never the full text. The proof is three tests:

  ```powershell
  py -m pytest tests/test_upload_api.py -k deleted
  ```

  `test_large_upload_is_deleted_before_claude_is_called` uploads a 1.5 MB PDF and checks that the temporary folder is already empty when the (fake) Claude call starts, and still empty afterwards. `test_failed_large_upload_is_deleted` does the same for a damaged file, and `test_file_just_over_10_mb_is_413_and_deleted` for a refused one.
- **The browser's ID:** the `spartan.clientId` key in the browser's localStorage (DevTools, Application, Local storage). Clearing the site's data makes a new ID, and the old classes stop showing.
- **The API key:** only in `.env`, read by `backend\config.py` when the server starts. The frontend never sees it.
- **Logs:** only in the PowerShell window running the server. There are no log files.

## Check the key is nowhere else

From the project folder:

```powershell
Get-ChildItem -Recurse -File -Force | Where-Object { $_.FullName -notmatch '\\\.venv\\|\\__pycache__\\' -and $_.Name -ne '.env' } | Select-String -Pattern 'sk-ant[-]'
```

No output means no file except `.env` holds anything that starts like an Anthropic key. It skips `.venv` (installed packages), `__pycache__` (compiled copies of the code) and `.env` itself. The pattern is written as `sk-ant[-]` so this README doesn't match its own command, and the tests use fake keys that don't look like real ones, so nothing shows up.

## Limits and rules

- **What it reads:** one PDF or Word (.docx) file per upload, up to 10 MB, or pasted text. The file's name and its first bytes must agree (a `.pdf` must really be a PDF). Old `.doc` files aren't read: save them as `.docx` first.
- **How much text:** up to 150,000 characters, and at least 50 that aren't spaces. A PDF with no text layer (a scan) gets "I couldn't find any text in that file", with a hint to paste the text. Password-protected or damaged files get "I couldn't open that file".
- **Word files:** the body, the tables (one line per row) and the header are read, including a separate first-page header when the file has one. Text boxes, footnotes and footers are skipped.
- **10 syllabi per browser per day:** counted over the last 24 hours from saved syllabi, so a failed upload doesn't count. The message says roughly when you can try again.
- **50 uploads per network (IP address) per day:** counted in the server's memory only. It's never saved and never logged, and a restart resets it. Every attempt that reaches the Claude step counts, even if Claude fails. Uploads turned away earlier (wrong type, too big, too short) don't.
- **Class names:** taken from the syllabus. If it doesn't state one, the file name is used ("cs_101-fall.pdf" becomes "cs 101 fall"), and pasted text becomes "Pasted syllabus". Rename takes 1 to 120 characters, with extra spaces tidied.
- **The year:** taken from the term the syllabus states ("Fall 2026"). If it states no term or year, Claude uses the term in progress or about to start on the upload date.
- **Never guess a date.** A date is kept only when Claude didn't mark it as vague and the quoted date phrase names exactly that day:
  - the month and day must match ("Wed, Oct 14", "10/14", "October 14th", "14-Oct", "10-14-2026" and "2026-10-14" all name Oct 14; a bare "10-14" doesn't);
  - a weekday, if there is one, must agree with the date ("Thu, Oct 14" in 2026 gives no date);
  - a phrase that covers several days gives no date ("Dec 7–11", "Oct 14 and Oct 16", "Oct 14, 16"). Times of day don't count, and a year after a comma isn't a second day, so "Monday, December 14, 9:45–12:00" and "Oct 14, 2026" still name one day;
  - the date phrase has to be inside the quoted sentence as whole words ("Oct 1" isn't inside "Oct 14"). The date words right next to it in the sentence count too, so a phrase Claude shortened can't hide a weekday, a year, a second day or "the week of": "Dec 7" quoted from "Dec 7–11" gives no date.

  Three more checks (added during this build, approved Nov 15): a year in the phrase must match ("10/14/2025" can't support 2026-10-14), two possible days give no date ("Oct 14 or 16", "Oct 14/16"), and "the week of" or "every" give no date.

  The term check (approved Nov 15): when the syllabus states a term with a year, the date must fall inside it. Fall runs August to December, Spring January to May, Summer May to August, and Winter December of the year before through January. So a "Fall 2026" syllabus can't end up with 2025-10-14. The check is skipped when no term with a year is stated, or when the term Claude read isn't actually in the syllabus. Anything that fails a check shows under "Needs a date".
- **Source check:** every quoted sentence is looked up in the syllabus text, ignoring spacing and line breaks, curly vs straight quotes, dashes and hyphens, invisible characters and capital letters. If it isn't there, the item is kept with the warning "I couldn't find this exact sentence in your syllabus. Double-check it." A quote shorter than 6 characters never counts as found.
- **Weights:** kept only when above 0 and at most 100 percent. The prompt tells Claude to leave a group's weight ("Quizzes 10%") off each quiz and never to work one out.
- **Repeats:** items with the same title and type are kept once per date. An undated one is dropped only when its sentence is a copy of one already kept (the same sentence, or part of it). Different lines that share a name, such as "Lab report due" in Week 3 and in Week 7, all stay.
- **Sizes:** titles are cut at 200 characters and quotes at 2,000. The file name is stored without its folder path, up to 255 characters.
- **Saved:** for each syllabus, the class name, the file's own name, the model, the prompt version and the time. For each deadline, the title, type, date, date phrase, weight, source sentence, whether the date was vague, whether the quote was found, and the status ("unchecked" until build 2). Not saved: the file, the full text, names, emails, IP addresses.
- **Sent to Anthropic:** the syllabus text and today's date. Nothing else: no browser ID, no IP address, no file name.
- **Word files that unpack to more than 50 MB** are refused, so a tiny upload can't balloon in memory (added during this build, approved Nov 15).
- **PDFs stop being read** once their text passes 1,000,000 characters, so a tiny file whose pages all repeat one huge page can't tie up the server. It gets the same "too long" message as any long syllabus.

## Project layout

```
.env.example           settings template (copied to .env, which holds your key)
requirements.txt       pinned packages the app needs
requirements-dev.txt   those plus pytest
pytest.ini             test settings (the live test only runs with -m live)
backend/
  main.py              app setup: one error format, body size limit, serves frontend/
  config.py            settings from environment variables and .env
  errors.py            every error code and its message
  schemas.py           data shapes: Claude's reply, cleaned items, API responses
  prompts.py           the Claude prompt (v1) and the field descriptions in its reply schema; every prompt lives here
  clock.py             "now" in one place, so tests can freeze time
  db/
    connection.py      opens SQLite and applies migrations
    repository.py      every SQL query
    migrations/001_initial.sql
  routes/
    deps.py            browser ID check, database connection, extractor
    syllabi.py         POST and GET /api/syllabi, PATCH /api/syllabi/{id}
    items.py           GET /api/items
  services/
    text_extraction.py PDF and Word to text
    extraction.py      the Claude call
    postprocess.py     the checks on Claude's answer
    source_check.py    is the quote really in the syllabus?
    dates.py           does the date phrase name that day?
    terms.py           which days the stated term covers
    rate_limit.py      the per-network limit, in memory
frontend/
  index.html
  css/                 tokens.css (colors, fonts), base.css, upload.css, dates.css
  js/
    app.js             startup and the #/ and #/dates routes
    api.js             the only file that talks to the server
    client-id.js       the browser's random ID
    format.js          dates, numbers and labels through Intl
    class-colors.js    one color per class, by upload order
    announce.js        status messages for screen readers
    icons.js           inline icons and a safe element builder
    screens/upload.js  the upload screen
    screens/dates.js   the dates screen
tests/
  fixtures/            sample syllabus (text, PDF, HTML), a fake Claude reply, the expected result
  test_*.py
data/                  the SQLite database (created on first run, gitignored)
```

## Troubleshooting

**"Activate.ps1 cannot be loaded because running scripts is disabled on this system."** Run this, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

It only affects the current window, so you need it again in each new window that complains.

**Wrong Python.** Signs: "No module named uvicorn" (or fastapi, or pytest), or the `sys.prefix` check prints something other than `C:\Projects\spartan-planner\.venv`. The venv isn't active in this window, so `py` picked the newest Python on the PC (3.14), which has none of the packages. Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

To see every Python `py` knows about (the line with `*` is the one it uses):

```powershell
py -0p
```

With the venv active, this should say Python 3.13:

```powershell
py --version
```

If the venv itself was made with the wrong version, delete it and redo Setup from step 1. This only removes the installed packages: your code and `.env` stay.

```powershell
deactivate
```

```powershell
Remove-Item -Recurse -Force .venv
```

**Port 8000 in use.** Starting the server fails with `[WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions` or `[WinError 10048] Only one usage of each socket address...`. Something else, often another window still running this app, holds the port. See what it is:

```powershell
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess
```

Stop that server (Ctrl+C in its window), or run this one on another port and open http://127.0.0.1:8001:

```powershell
py -m uvicorn backend.main:app --reload --reload-dir backend --no-access-log --port 8001
```

**"I'm not set up to read syllabi yet: the server is missing its API key."** `.env` has no key, or the server started before you added it. Add the key with `notepad .env`, then press Ctrl+C and start the server again. "...the server's API key didn't work" means Anthropic rejected the key: check it in the Anthropic console.

**A frontend change doesn't show up.** The browser kept an old copy. Press Ctrl+F5.

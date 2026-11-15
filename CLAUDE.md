# Spartan Planner

A web app that turns course syllabi into a semester plan. A student uploads syllabi, the app finds every deadline and shows the exact sentence it came from, the student confirms each date, and the app builds a backward plan and warns about weeks where work piles up across classes. Built by one SJSU student for other SJSU students, with input from the Accessible Education Center. Testers get a link on Nov 18, 2026.

## Stack
- Python 3.13, FastAPI, SQLite. One deployable unit.
- Frontend is plain HTML, CSS and JavaScript modules served by FastAPI. No build step, no framework.
- Anthropic Claude API for extraction only. All prompts live in one file, backend/prompts.py.
- I develop on Windows with Windows PowerShell 5.1. Give PowerShell commands, never bash. Run Python with the `py` launcher, not `python`.
- Hosting is Railway with a persistent volume for the SQLite file.
- Pin dependency versions. Keep dependencies few.

## Code structure
- Split code into small focused modules. No long single-file scripts.
- Suggested layout: backend/ (main.py, routes/, services/, db/, prompts.py, config.py), frontend/ (index.html, css/, js/ with one module per screen), eval/, analysis/, tests/.
- Keep a README with Windows setup steps and a short CHANGELOG.

## Privacy rules (do not weaken these)
1. The extended-time multiplier never reaches the server. It lives in the browser's localStorage. It is never in a request body, query string, header, log line or database column.
2. Because of rule 1, all planning math that uses the multiplier runs in the browser: time estimates, the backward plan, the crunch score, and the calendar file.
3. The server never stores durations of planned blocks, since they would reveal the multiplier.
4. No accounts. On first visit the browser creates a random ID, stores it in localStorage, and sends it in an X-Client-Id header. All rows are keyed by it. Never ask for a name or email.
5. Never ask for or store diagnosis, health or accommodation details. The multiplier screen asks only for a number and says no reason is needed.
6. Uploaded files are deleted after extraction. Keep only extracted items and their source sentences.
7. The Anthropic API key lives only in an environment variable on the server. Never in frontend code, never committed. Add .env to .gitignore before the first commit.
8. Never guess a date. If the syllabus is vague, return the item with no date and flag it for the student.

## Flow
1. Upload syllabi.
2. One question per screen: free study hours per week, then extended time (1x, 1.5x, 2x, or a custom number). Both answers stay in the browser.
3. Check each date, one card at a time, next to its source sentence. Confirm, fix, or save for later.
4. Plan screen: countdown to finals, crunch warning, load per week by class, an "Up next" task, calendar export.

## Look and voice
- Dark mode is the default. Background #0D0F1C, cards #171A2C, raised #1F2340, borders #2C3155, text #F3F1FF, muted text #A7ACC8, accent lime #C8F560, warning amber #FFB547, cheer purple #9B8CFF.
- Class colors, always shown with the class name: #7AA2FF, #FF8FB1, #6EE7B7, then cycle.
- Headings in Bricolage Grotesque 800. Body in Atkinson Hyperlegible. Load both from Google Fonts.
- The app speaks in the first person, short and friendly. Examples: "Feed me your syllabi." "Real talk: do you get extended time?" "Quick gut check." "I didn't guess. When is it actually due?"
- Warnings are gentle and specific, never alarming. Pattern: "Hey! Dec 7 to 11 is stacked." Then what lands that week, the hours needed against the hours free, and one action.
- One main thing per screen. Large tap targets. A visible progress indicator through setup.
- Motion: cards slide, checks pop, bars grow. Animate transform and opacity only. Wrap all motion in a prefers-reduced-motion check and turn it off for users who ask for less.
- Works on a laptop and a phone. Setup and the plan view get a wider layout on a laptop.

## UI quality bar
- Full keyboard support with visible focus rings. Never remove an outline without a replacement.
- Hit targets at least 44px on mobile. Inputs at least 16px font size. Never disable zoom.
- Native elements first: button, a, label, input. Icon-only buttons need an aria-label.
- Status is never shown by color alone. Add a text label or icon.
- Errors appear inline next to the field. Use polite aria-live for toasts.
- Design empty, loading and error states for every screen. No dead ends.
- Dates and numbers go through Intl.DateTimeFormat and Intl.NumberFormat.
- Long class names and long source sentences must wrap or truncate cleanly.
- Set color-scheme: dark on the html element.
- Every generated value (date, type, weight, hours) is editable by the student.

## How we work
- Before writing code in a session, list the files you will create or change and ask me anything you need answered.
- Build in stages and stop at the end of each prompt so I can test.
- Ask before adding any rule or default that changes how the app behaves. Do not add features that are not in the prompt.
- Out of scope for v1: accounts, Canvas integration, a chat interface, grade tracking, flashcards, timers beyond the sprint button, a mobile app, reminder notifications, support links.

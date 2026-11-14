# Smoke checklist (M2 slice 6)

The manual checks that the automated suites can't make: a real phone, real browsers, the
deployed services and their logs. Decided in PLAN.md (Q61, Q67, Q68, Q71, Q80).

**This file holds criteria only.** It is committed before any run, and that commit fixes the
criteria. A later change gets a dated note under [Changes](#changes); it never edits a criterion
after a result was recorded against it.

**Results go in a separate file per run:** `docs/smoke-results/YYYY-MM-DD.md`, never here. Each
results file starts with the commit SHA under test (the `release` commit for prod), the device
and browser (with versions), and the network as a description. Then one line per item: ID, pass
or fail, and a short note (what was seen, timings where asked).

**What a results file must never contain:** real IP addresses, Wi-Fi network names (SSIDs),
device serial numbers, or account names and emails. Networks are written "home Wi-Fi" or
"mobile data", devices by make and model. The only IP address allowed is `203.0.113.77`, the
documentation-range address used as the forged header in S21.

**Where it runs:**
- **local pre-pin**: on this machine before the release commit is pinned, against a local
  production build (`npm run build` then `npm run start` in `frontend/`, with the local API).
  A failure here is fixed before the pin.
- **prod**: against the deployed URLs (Vercel page, Render API), after step 5, with the browser
  console open for every item.
- **both**: once in each place.

Each item: **Action**, **Expected**, **Pass if** (yes or no, nothing in between).

## Page and repos

### S1 First load
- **Where:** both
- **Action:** open `/` in a fresh private window with the network panel open; then pick another
  suggested question.
- **Expected:** the header, the itsdangerous flagship stored answer with its label, the cited
  code (side panel on desktop), the suggested questions; any "waking" line ends by itself. The
  picked question's stored answer appears at once.
- **Pass if:** the flagship answer is visible without a reload, no error message is shown, the
  console shows no errors, and the pick makes no request to `/ask`.

### S2 Repo switch
- **Where:** both
- **Action:** pick `psf/requests` in the repo selector, then press the browser's Back button
  once.
- **Expected:** the requests flagship answer; the address becomes `/?repo=psf/requests`; Back
  leaves the site (or returns to the page before it), because a switch adds no history entry.
- **Pass if:** all three hold.

### S3 `?repo=` links
- **Where:** both
- **Action:** in new tabs open `/?repo=expressjs/express`, `/?repo=PSF/Requests` and
  `/?repo=nope/nope`.
- **Expected:** the express flagship; the requests flagship with the address normalised to
  `/?repo=psf/requests`; the default repo with the address `/`.
- **Pass if:** all three hold.

## Answers

### S4 Grounded question and citation click-through
- **Where:** both
- **Action:** on itsdangerous ask "How does the signer derive its key?"; click the first
  verified citation chip; click "View on GitHub".
- **Expected:** an answer with citation chips; the panel (or the phone's sheet) shows the cited
  lines highlighted; GitHub opens in a new tab at the pinned commit on the same lines.
- **Pass if:** the highlighted lines equal the chip's range and GitHub shows the same file and
  lines at the pinned commit.

### S5 Ungrounded answer
- **Where:** both
- **Action:** ask "What is the capital of France?".
- **Expected:** "No cited answer for this question", no answer text, a list of the closest
  files; each link opens github.com in a new tab.
- **Pass if:** the heading is shown, no answer text is shown, and every link opens a
  `https://github.com/` page in a new tab.

## Limits and refusals (prod only; within Q62's budget of answered questions)

### S6 Per-visitor limit
- **Where:** prod
- **Action:** with `admin --prod per-ip 1` and one answered question already from this network,
  ask again; also send the same request with `curl -i`.
- **Expected:** the per-visitor message, with no "Try again" button.
- **Pass if:** the page shows the per-visitor message, and the reply is `429` with
  `"error": "per_ip_limit"`, a `Retry-After` header and `Cache-Control: no-store`.

### S7 Budget exhausted
- **Where:** prod
- **Action:** set the budget below today's use (`admin --prod budget <n>`), ask a question,
  also with `curl -i`; then restore the budget.
- **Expected:** the daily-limit message saying when to try again.
- **Pass if:** the page shows the daily-limit message, and the reply is `429` with
  `"error": "daily_limit"` and `Cache-Control: no-store`; after the restore, `admin --prod
  status` shows the restored value.

### S8 Kill switch (Q71)
- **Where:** prod
- **Action:** `admin --prod pause`; wait up to 30 s; reload the page; `curl -i` a POST to
  `/ask` and a GET of `/status`; then `admin --prod resume`.
- **Expected:** the paused message on the page; `/ask` refuses; `/status` says paused; after
  resume, `/status` says ok.
- **Pass if:** within 30 s the page shows the paused message; `/ask` replies `503` with
  `"error": "paused"`, no `Retry-After` and `Cache-Control: no-store`; `/status` says `paused`
  with `Cache-Control: no-store`; after resume `/status` says `ok`.

## Accessibility and layout

### S9 Keyboard walk
- **Where:** both
- **Action:** with the keyboard only, Tab from the top: skip link, question box, Ask, the
  answer's chips, the evidence panel and its citation list, the suggested questions, the header
  links.
- **Expected:** every control is reached; the focus outline is always visible.
- **Pass if:** every control is reached by Tab, and no focused control is hidden (including
  under the sticky composer).

### S10 Real phone: the ask box with the on-screen keyboard (Q61)
- **Where:** prod
- **Action:** on the phone named in the results file, tap the question box so the on-screen
  keyboard opens.
- **Expected:** the question box and Ask stay visible above the keyboard.
- **Pass if:** both are fully visible without scrolling.

### S11 Overflow at 320 and 390 px
- **Where:** both
- **Action:** in the browser's device mode at 320 and at 390 px wide, ask a question that is
  one long unbroken URL, then open an ungrounded answer.
- **Expected:** the question heading and the file links wrap inside the column.
- **Pass if:** at both widths the page never scrolls sideways.

### S12 Forced colours
- **Where:** both
- **Action:** turn on forced colours (Windows contrast theme, or the browser's forced-colors
  emulation); open a cited answer and the suggested questions.
- **Expected:** cited code lines keep their left bar; the current suggestion has its bar.
- **Pass if:** both bars are visible.

## Privacy and sharing

### S13 Privacy link and text
- **Where:** both
- **Action:** click "Privacy" in the header and in the composer note; read `/privacy`; open
  each policy link.
- **Expected:** `/privacy` opens in a new tab; its text is `PRIVACY` from
  `frontend/lib/messages.ts` at the commit under test; the composer note carries `PRIVACY.short`.
- **Pass if:** the page text matches the constant word for word, both links open `/privacy` in
  a new tab, and every policy link loads its provider's page.

### S14 Link preview
- **Where:** prod
- **Action:** paste the production URL into LinkedIn's Post Inspector and into a Slack message.
- **Expected:** title "CodeAsk", the description, the 1200×630 card image.
- **Pass if:** both show the title and the image. (Run again after the first-share deploy,
  step 8.)

## Headers, routes and CORS

### S15 CSP report-only, then enforced
- **Where:** prod
- **Action:** with `CSP_MODE` unset (report-only) and the console open, run S1 to S13 and open
  every page state (answered, ungrounded, error, paused, daily limit, per-visitor, in progress,
  stored answer, mobile sheet, both themes). Then set `CSP_MODE=enforce`, redeploy, `curl -I`
  the page, and repeat S1, S2 and S4.
- **Expected:** no CSP messages in report-only; after the redeploy the header is
  `Content-Security-Policy`, not `Content-Security-Policy-Report-Only`; the short smoke works.
- **Pass if:** zero CSP violation messages in both phases, and `curl -I` shows the enforced
  header.

### S16 Health and routes
- **Where:** both
- **Action:** `curl -i` GET and HEAD on the API's `/` and `/health`; GET on `/docs`, `/redoc`,
  `/openapi.json`.
- **Expected:** `/` and `/health` answer; the documentation routes don't exist.
- **Pass if:** `/` and `/health` give `200` for GET and HEAD, and the three documentation
  routes give `404`.

### S17 CORS refusal
- **Where:** prod
- **Action:** `curl -i` GET `/status` with `Origin: https://example.com`, then with the Vercel
  production origin; repeat both as an `OPTIONS` preflight for `POST /ask`.
- **Expected:** only the Vercel origin is allowed.
- **Pass if:** the foreign origin gets no `Access-Control-Allow-Origin` header in either
  request, and the Vercel origin gets `Access-Control-Allow-Origin` equal to itself in both.

## Logging (Q68)

### S18 Canary
- **Where:** prod
- **Action:** ask one question containing a unique marker (for example
  `canary-<date>-<random>`); then search for the marker in Render's logs and in every text
  column of every table in the prod database; open Vercel's logs for that page load.
- **Expected:** the marker is nowhere; Render's log shows only the app's request line for the
  question; Vercel's page-load logs hold no question text (`/ask` goes from the browser to
  Render, so Vercel never receives it).
- **Pass if:** zero hits for the marker in Render's logs, in the database and in Vercel's logs.

## Q80 items (local, before the pin)

### S19 Identifiers in the question box on the real phone
- **Where:** local pre-pin, on CodeAsk's own composer (a plain text box wouldn't test our
  attributes). Setup: only the frontend dev server is bound to the home network, for the
  minutes the check takes; the backend stays on `127.0.0.1`; the server is stopped afterwards
  and any firewall rule it needed is removed. **I confirm the network exposure before running
  it.** The attributes as shipped are pinned by an e2e test (`keyboard.spec.ts`, "the question
  box's autocapitalize, autocorrect and spellcheck are as shipped").
- **Action:** on the real phone, type `etag` and `req.fresh` into the question box.
- **Expected:** both stay exactly as typed.
- **Pass if:** neither is autocorrected or capitalised. If either is, `autoCorrect="off"` and
  `autoCapitalize="off"` go on the textarea (and the e2e test's expected values change with
  them), a code change before the pin, and S19 runs again.

### S20 The repo select in Windows dark mode
- **Where:** local pre-pin
- **Action:** on the author's Windows machine with the dark theme on (the site's toggle and the
  system setting), open the repo select.
- **Expected:** the options popup is legible.
- **Pass if:** every option's text is readable against the popup's background (not dark on
  dark or light on light).

## Launch checks (prod; Q61, Q62, Q66, Q67, Q70)

### S21 IP gate (Q67; runs first among the prod checks)
- **Where:** prod
- **Action:** the Q67 procedure: `per-ip 1`; from network A one accepted question and one
  refused; from network B one question; from A a request with a forged `CF-Connecting-IP` set to
  a never-used address.
- **Expected:** the API keys visitors by Render's client IP, not by a header the client sends.
- **Pass if:** A's second question is refused with `per_ip_limit`, B's question is accepted,
  and the forged request is refused with `per_ip_limit`.

### S22 Cold starts (Q61)
- **Where:** prod
- **Action:** three times, after at least 15 minutes idle, open the page and ask one question.
  Record the time from the first `/status` to its first `200`, and to the first answer.
- **Expected:** the waking message, then ready; the first question works.
- **Pass if:** each time the waking state is shown, no raw error appears, and the first
  question is answered without a manual reload.

### S23 Pinned commits (Q66)
- **Where:** prod
- **Action:** GET the API's `/repos`.
- **Expected:** each featured repo at its pinned commit.
- **Pass if:** every `commit_sha` equals the one in `frontend/data/featured.json`.

### S24 Grants (Q70, Q76)
- **Where:** prod
- **Action:** `python -m codeask.admin --prod grants codeask_api --check`.
- **Expected:** the API role has exactly the expected privileges and nothing else.
- **Pass if:** the check passes.

### S25 `noindex` before and after the first share
- **Where:** prod
- **Action:** `curl -I` the page before step 8, and again after the first-share redeploy.
- **Expected:** `X-Robots-Tag: noindex` before; no `X-Robots-Tag` after.
- **Pass if:** both hold.

### S26 Final state
- **Where:** prod
- **Action:** after the checks, wait more than 30 s, then `admin --prod status`.
- **Expected:** the launch settings.
- **Pass if:** not paused, budget 170000, per-ip 5.

## Changes

- **2026-11-14 (before any run):** two states in PLAN.md's slice 6 done-when list, "unverified
  display" and "busy", are covered by named e2e tests on the mocked API, not by live items here:
  whether they happen live depends on what the model writes and on queue load, so a live item
  could not be made to pass or fail on demand. The tests (`frontend/tests/e2e/`):
  - unverified: `ask.spec.ts` "the first VALID citation is pre-opened, never an unverified
    one" and "an unverified chip toggles its inline note and leaves the panel alone";
    `a11y.spec.ts` "axe: unverified note open, light" and "…, dark".
  - busy: `ask.spec.ts` "busy: a countdown from Retry-After, then a manual retry, never an
    automatic one" and the two "busy with / WITHOUT Access-Control-Expose-Headers" cases;
    `a11y.spec.ts` "axe: busy, light" and "…, dark"; the queued variant in `queue.spec.ts`.

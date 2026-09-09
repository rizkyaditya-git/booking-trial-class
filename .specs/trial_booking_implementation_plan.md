# Trial booking implementation plan

> Execution is inline in this session using `superpowers:executing-plans`. Do not delegate implementation or reviews to subagents. This document does not authorize execution; wait for an explicit instruction to start.

**Goal:** Deliver the trial-booking flow with reproducible failure, duplicate, capacity, and last-seat checks.

**Architecture:** API and HTML routes call plain functions in `bookings_svc.py`. SQLite owns durable constraints; the service completes payment and confirmation in one transaction. The roster reads confirmed bookings.

**Tech stack:** FastAPI, Jinja, plain CSS, standard-library SQLite and logging, pytest, httpx, Ruff.

**Spec:** [Trial booking solution](trial_booking_solution.md) defines behavior and acceptance criteria. This plan is the only checklist for remaining implementation and submission work.

Repository root: `C:\Users\rizky\Documents\personal\booking-trial-class`. All file and directory paths below are relative to this root.

## Execution rules

- Implement inline, task by task. Give brief progress updates; pause for blockers, scope changes, required approval, or the time cap.
- No overtesting: cover each distinct business rule or failure mode with a focused check. Reuse cases and parametrization; do not repeat the business matrix at every layer, test framework internals, or add stress loops and coverage targets.
- No over-reviewing: check each change while working, then make one final acceptance pass. Do not add reviewer agents, repeated review rounds, or approval gates after every task.
- Run affected tests during development and the full suite/lint at final verification. Rerun checks only after failures or relevant changes. Keep all [acceptance and safety checks](trial_booking_solution.md#acceptance-checks).

## Global constraints

- Cap total assessment work at four hours, including planning, verification, documentation, and the video. Record unfinished work when time expires.
- Use SQLite 3.37 or later, five STRICT tables, capacity four, and a five-second busy timeout.
- Keep the [agreed file responsibilities](trial_booking_solution.md#folder-structure). API and page routes must not duplicate booking rules.
- Use synthetic data, demo-parent context, and deterministic mock payments. No Stripe, real authentication, deployment, ORM, or frontend build step.
- Preserve existing edits. Commit or push only after an explicit request.
- Use a focused failing check before changing behavior, then rerun it after the change. The commands below are planned, not reported results.

## Timebox

Planning took approximately two hours. Target the remaining work within two hours, respecting the four-hour total cap. Prioritize backend correctness and preserve time for verification, documentation, and the video. Record actual time and unfinished work in README.

## 1. Database and runnable setup

| When | Exact paths |
| --- | --- |
| Start task 1: create directories | `app/`, `app/api/`, `app/schemas/`, `app/services/`, `app/db/`, `app/templates/`, `app/static/`, `tests/` |
| Start task 1: create empty package files | `app/__init__.py`, `app/api/__init__.py`, `app/schemas/__init__.py`, `app/services/__init__.py`, `app/db/__init__.py` |
| During task 1: implement these files | `pyproject.toml`, `app/db/connection.py`, `app/db/schema.sql`, `app/db/seed.sql`, `tests/conftest.py`, `tests/test_bookings.py` |
| Explicit database setup: generate local data | `var/` and `var/trial-booking.sqlite3`; do not create an empty database during scaffolding |

Preserve existing directories and files. Do not add `__init__.py` under `tests/`, `app/templates/`, or `app/static/`. Update the existing `.gitignore` only for generated files. Tasks 2-4 list the remaining implementation files; create them in those tasks, not as empty placeholders in task 1.

Produces an initialized SQLite file and one connection per operation. `tests/conftest.py` provides a fresh seeded `db_path` under `tmp_path`; no test uses the demo database.

- [ ] Create the eight directories and five empty package files listed above, without overwriting existing files.
- [ ] Pin the runtime/dev dependencies and record the tested Python and SQLite versions. Check current documentation when choosing version-specific APIs.
- [ ] Write and run seed/constraint checks before adding the schema. Confirm failures come from the missing behavior.
- [ ] Implement the five tables and every [constraint](trial_booking_solution.md#constraints), including explicit null checks, pending inserts, terminal-state guards, and partial unique indexes.
- [ ] Seed through valid transitions. Identify the available class, three-confirmed class, duplicate pair, payment-failure booking, and both demo parents in README.
- [ ] Provide explicit setup/reset commands. Reset must target only the selected demo database and require an explicit option; ordinary startup preserves data.
- [ ] Rerun the checks against a fresh file. Verify a second setup cannot silently erase existing bookings.

Run: `python -m pytest tests/test_bookings.py -q`

## 2. Booking logic and race proof

Create `app/services/bookings_svc.py` and `tests/test_race.py`; extend `tests/test_bookings.py` and `tests/conftest.py`.

Consumes the database connection/setup from task 1. Produces shared operations for parent/child/class reads, booking creation/read, payment completion/read, and confirmed rosters. Inputs and returned fields follow [API contracts](trial_booking_solution.md#api-contracts); keep HTTP response formatting in routes.

- [ ] Write failing flow checks: pending booking, successful confirmation, failed payment with unchanged roster, duplicate rejection, and full-class rejection.
- [ ] Implement ownership, scoped request keys, and the exact [creation](trial_booking_solution.md#request-keys-and-booking-creation) and [payment transaction](trial_booking_solution.md#payment-flow) order. Commit expected blocked outcomes; roll back unexpected failures.
- [ ] Add replay checks for same/changed input, separate key scopes, unchanged timestamps, and fresh keys against terminal bookings.
- [ ] Write the ordered race: A starts, B starts and confirms, then A records `blocked/class_full`. Reread the database and roster.
- [ ] Implement the [concurrent test coordinator](trial_booking_solution.md#race-tests) using separate connections to one file. Cover last seat, same child with spare capacity, and identical request keys. Do not use sleeps or production test hooks.
- [ ] Inject rollback and lock-timeout failures. Check that the attempt, booking, and key remain consistent, then retry after removing the fault.
- [ ] Run the focused suite. One winner and one recorded block must leave exactly four confirmed students; an unexpected exception or timeout is not a passing race result.

Run: `python -m pytest tests/test_bookings.py tests/test_race.py -q`

## 3. JSON API and diagnostics

Create `app/main.py`, `app/api/bookings.py`, `app/schemas/bookings.py`, and `tests/test_http.py`; extend `tests/conftest.py`.

Consumes the shared service operations. Produces the nine [JSON routes](trial_booking_solution.md#json-routes), declared request/response models, and centralized errors. The HTTP fixture uses the same fresh database and `TestClient` with `follow_redirects=False`.

- [ ] Write failing HTTP checks for a complete booking/payment/roster flow and the documented error responses.
- [ ] Implement demo context, strict payload/query validation, request keys, envelopes, Problem Details, `Location`, request IDs, and no-store headers. Match the spec's success/replay/conflict statuses.
- [ ] Add [JSON logs and read-only health](trial_booking_solution.md#monitoring). Check missing files/tables, sensitive-field exclusion, and post-commit outcome logging.
- [ ] Keep `/docs` and `/openapi.json` at their default paths. Check OpenAPI against the route table and reject trailing-slash variants.
- [ ] Run HTTP checks; rerun service tests only if shared logic changed. Restart the app and confirm existing bookings survive.

Run: `python -m pytest tests/test_http.py -q`

## 4. Three Jinja pages

Create `app/api/pages.py`, `app/templates/base.html`, `app/templates/book_trial.html`, `app/templates/booking_status.html`, `app/templates/roster.html`, and `app/static/styles.css`; extend `tests/test_http.py`.

Consumes the same service operations as the JSON routes. Produces the five [HTML routes](trial_booking_solution.md#html-form-routes) and CSS at `/v1/static`.

- [ ] Write failing form checks for submission/payment redirects and inline errors. Follow each `303` with GET; refreshing must not write.
- [ ] Adapt [layout A](ui/layout-a.html) into three separate templates. Replace sample values and preview controls with backend data. Keep stacked choices, native controls, keyboard focus, and status wording.
- [ ] Preserve demo-parent context per page, submitted values, and request keys on recoverable errors. Show payment buttons only for pending bookings.
- [ ] Rerun affected HTTP checks. Compare the pages with the [approved screenshots](trial_booking_solution.md#approved-ui-references) during the final browser walkthrough in task 5.

Run: `python -m pytest tests/test_http.py -q`

## 5. Final verification

Fix only defects found in the implemented files/tests. Record actual commands and results in `README.md` and `AGENTS.md`.

- [ ] Run documented setup in one clean checkout, or a clean copy of the submission files before publication, with a fresh environment. Confirm no secrets, existing database, or ignored artifact is needed.
- [ ] Run the full suite and both lint/format checks in that environment. Fix failures, then rerun the affected checks and any final checks invalidated by the changes.

```sh
python -m pytest -q
ruff check .
ruff format --check .
```

- [ ] Make one browser walkthrough covering all four required seed cases, the ordered A/B race, and the approved UI states. Check the roster after each outcome. Record this walkthrough for task 6 instead of repeating it.
- [ ] Complete the [acceptance checks](trial_booking_solution.md#acceptance-checks), including the chosen mechanism regressions. Report browser proof separately from automated test results.

## 6. Documentation, video, submission

Complete `README.md` and `AI_USAGE.md`; mark only completed work in this plan.

- [ ] Complete the existing README sections: verified setup, built scope, seed IDs, schema, routes/statuses, rule placement, race approach/why/tradeoffs, assumptions, actual time, cuts, monitoring, and next steps.
- [ ] Answer all six AI_USAGE questions with concrete examples and actual verification. The rejected Stripe integration or corrected missing model concepts are available examples; do not invent results.
- [ ] Use the recorded task 5 walkthrough for the required 5 to 8 minute video. Include startup/seed overview, successful booking and roster, duplicate/payment failure, A/B last-seat outcome and race tests, then transaction design and cuts.
- [ ] Watch the video and check that text and audio are readable. Use synthetic data and keep credentials out of the recording.
- [ ] Review the public submission files, then commit/push only if requested. Confirm published files match the verified submission and check repository/video access without reviewer credentials. Repeat setup/tests only if submission contents changed. Submit both links, not a zip.

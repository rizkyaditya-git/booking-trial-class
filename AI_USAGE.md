# AI usage

## Tools I used

- OpenAI Codex for the interactive implementation. No implementation or reviewer subagents were used.
- Context7 for current FastAPI documentation.
- Playwright CLI to drive Chrome for verification.

These tools are not application runtime dependencies.

## What I used AI for

I used AI to implement the approved design and checklist:

- SQLite schema and seeds.
- Shared booking functions and API contracts.
- Jinja pages based on the approved stacked-choice reference.
- Focused tests and handoff documentation.

The implementation retained the approved file responsibilities.

## Where AI saved time

- Codex implemented the test-only concurrency coordinator with a held SQLite controller lock and trace-callback events. It exercises two real connections without sleeps or production hooks, then rereads persisted results. The same coordinator covers last-seat contention, competing bookings for one child, and identical payment keys.
- Tests caught three implementation defects: content-type middleware masked 404/405 responses, HEAD handling lacked an import, and form validation lost values because FastAPI supplied a mapping rather than a plain dict. Each affected check was rerun after the fix.

## Where I pushed back

- I rejected Stripe after investigating it during design. Reviewer-managed credentials and webhook setup would consume the assessment's limited time, so the approved solution uses a deterministic local mock.
- I required plain shared `bookings_svc.py` functions, the exact scaffold, no subagents, and focused verification instead of additional layers or repeated reviews.

## What I would change next time

Approximately half the four-hour budget was already spent before implementation. Next time I would:

- Set a shorter planning cutoff and reach a runnable transaction/race check earlier.
- Retain the acceptance criteria, but defer incidental detail until an end-to-end flow runs.
- Reserve a fixed recording/submission window from the start.

## How I verified the final work

Everything below is a check Codex ran while implementing. I did not repeat any of it by hand afterward.

- Before writing implementation code, it wrote checks that failed for the missing schema, service, JSON routes, and form routes, then reran the affected ones once the code existed.
- The database checks run against temporary real SQLite files. They cover the seed and SQL guards, ownership, replay, terminal protection, failure, capacity, rollback injection, and timeout/retry.
- It ran completions both in order and genuinely at the same time, through separate connections to a single file.
- On a fresh copy in a clean environment, all 81 tests passed in 14.47s. The 2 warnings came from third-party libraries rather than this code. Ruff lint reported no issues, and Ruff format found all 18 files already formatted, with the spec and steering docs excluded.
- It walked the app through Chrome: selection, the pending, success, failure, duplicate, and empty-roster states, the A-first/B-completes-first sequence, the rosters, and keyboard focus. It compared the screenshots against layout A and saved the browser evidence silently.
- It also checked sanitized errors, OpenAPI, request IDs, no-store headers, explicit setup behavior, rollback logging, and whether data survives an application restart.

The README documents both dependency warnings. Neither one failed a test.

Still on my list:

- Finish the narrated video, then review its audio and readability.
- Publish the repository and the video, then confirm both are publicly reachable.

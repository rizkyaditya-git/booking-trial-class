# Repository guidance

## Source of truth

- Read `README.md` for setup, behavior, and backend design before changing the implementation.
- Build only the trial-booking slice. Regular enrollment is outside this take-home.
- Keep the work within the stated four-hour timebox. Record unfinished ideas instead of expanding scope.
- If the implementation uses Python or a public API, read the applicable files in `.steering/` first. Apply their general rules, but do not copy quotation-specific examples or add abstractions solely to match the examples.

## Required behavior

- A parent can choose a child and an available trial class, submit a booking, record a mock payment result, and see the booking status.
- An admin or teacher can view the confirmed roster.
- A class must never have more than four confirmed students, including when two payment completions race for the last seat.
- A child must not have duplicate confirmed bookings for the same class.
- Failed payments must not create confirmed bookings or roster entries.
- Treat availability shown before payment as advisory. Recheck capacity atomically when confirming the booking.
- Enforce booking invariants in the backend and database where possible. UI checks are only early feedback.

## Implementation rules

- Before writing or changing code, invoke `ponytail:ponytail` at full intensity. Reuse existing code, standard-library or native features, and installed dependencies before writing the minimum new code needed.
- Prefer the smallest complete design and reuse existing code before adding helpers or dependencies.
- Use one clear transaction boundary for payment completion and seat confirmation. Do not rely on an in-memory count for concurrency safety.
- Keep statuses explicit and document allowed transitions. The roster includes confirmed bookings only.
- Use synthetic seed data for the required available-seat, three-confirmed-students, duplicate-attempt, and payment-failure cases.
- Keep secrets and real payment data out of the repository. The payment flow is a mock.
- Preserve unrelated worktree changes. Do not commit or push unless the user asks.

## Verification and handoff

- Add focused checks for duplicate confirmation, payment failure, capacity, and the last-seat race. The race check must prove that at most one competing completion is confirmed.
- Run the narrowest relevant checks after each change. Before completion, run the repository's documented test and lint commands and report the exact results.
- Until implementation exists, treat setup, run, test, and lint commands in `.specs/` as plans, not verified results. After implementation, record only commands that were actually run and their exact results.
- Keep `README.md` and `AI_USAGE.md` truthful and aligned with the implementation. Include the required setup, design, tradeoff, time-spent, monitoring, and next-step notes.
- Write concise technical prose with plain words, active voice, and specific claims. Do not report checks that were not run.

## Verified implementation

Tested with Python 3.11.15 and SQLite 3.53.1. Use the setup, run, test, and lint commands in `README.md`.

Clean-copy acceptance: 81 tests passed with two upstream TestClient/AnyIO deprecation warnings in 14.47 seconds; Ruff lint passed; Ruff format reported 18 files already formatted. Existing `.steering` and `.specs` references are excluded from Ruff so their illustrative snippets remain unchanged. Explicit `--reset` setup and overwrite refusal were also checked.

Chrome verification covered selection, successful and failed payment, duplicate rejection, empty/confirmed rosters, the ordered A/B race, and keyboard focus. The final narration, video review, publication, and public-link checks remain user work.

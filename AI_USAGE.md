# AI usage record

## Tools used

- OpenAI Codex desktop was used to inspect the repository, reason about the
  protocol, draft tests and implementation changes, review diffs, and prepare
  pull requests.
- Codex's in-app browser was used for local dashboard and WebSocket smoke
  checks.
- Git and GitHub CLI were directed through Codex to create isolated branches,
  commits, and pull requests in the detached candidate repository.

## Important prompts or prompt summaries

- Read `docs/protocol.md`, `docs/runtime-contract.md`, and `docs/api.md`, then
  consolidate their normative constraints into `AGENTS.md`.
- Work test first: reproduce one assignment failure at a time, show the failing
  evidence before implementation, apply the narrowest fix, and rerun focused
  and full checks.
- Correct event identity across boots with a data-preserving SQLite migration.
- Prove current-state ordering ignores device clocks and compares server boot
  generation before event sequence.
- Prove database ingestion precedes publication and suppress publication for
  duplicates, stale events, and transaction failures.
- Isolate slow WebSocket clients with bounded per-client buffering and restore
  authoritative state after dashboard connections.
- Keep each outcome in a reviewable pull request targeting `main`; do not merge
  pull requests unless explicitly instructed.

## Agentic workflow design

- Before implementation, I asked Codex to synthesize the three normative
  contracts into a repository-root `AGENTS.md`. This was deliberate context
  engineering, not a replacement for the source documents: the file explicitly
  makes those documents authoritative and turns their invariants, API promises,
  failure boundaries, and verification expectations into persistent guidance
  for every subsequent agent turn.
- Keeping this guidance in the repository reduced prompt drift across fresh
  branches and long-running work. It also made constraints such as opaque boot
  IDs, `(generation, sequence)` ordering, post-commit publication, bounded
  client memory, and data-preserving migrations visible at the point where AI
  generated or reviewed code.
- I directed Codex in short, auditable stages: read contracts, write one focused
  regression, observe the expected failure, explain the root cause, apply the
  smallest repair, run focused and full verification, inspect the diff, then
  publish a single-purpose pull request. I retained responsibility for scope
  choices, challenged ambiguous suggestions, and controlled every merge.
- Each later pull request was rebased onto the newly merged `main` before
  publication. This kept AI-assisted changes isolated to one behavioral outcome
  and made human review of both code and test evidence straightforward.

## Generated output rejected or corrected

- An initial AI attempt changed several areas before the requested workflow was
  agreed. That checkout was discarded, a clean clone was created, and all
  submitted work was redone one outcome at a time with failing tests first.
- Running normal and chaos simulators concurrently was rejected because both
  processes reuse the same device IDs and would distort the scenario. They were
  run sequentially instead.
- Adding a WebSocket transport dependency to project manifests was suggested
  after a local setup issue, then rejected as outside the requested repair
  scope. No dependency declaration was changed.
- A live automatic reconnect observation in the in-app browser was
  inconclusive because its background retry timer did not fire after restart.
  It was not reported as a pass; an automated reconnect-hook test and a
  separate snapshot/browser smoke check were used instead.
- Initial realtime test deadlines were widened from 100 ms to 500 ms to reduce
  CI timing risk without weakening the indefinitely-blocked-client regression.

## Verification performed

- The unchanged baseline compiled and passed its 7 starter tests.
- Event identity: 2 focused tests failed before the fix and passed afterward;
  the migration test opens a version-1 database and proves its audit row and ID
  survive while the same sequence from a new boot is accepted.
- Current-state ordering: 3 focused tests failed before the fix and passed
  afterward, covering delayed lower sequences, earlier device clocks, and
  events from older boot generations.
- Transaction/publication: 4 focused tests failed before the fix and passed
  afterward, checking call order, duplicates, stale events, and repository
  failure.
- Realtime safety: the blocked-client and missing-buffer tests failed before
  the fix; the existing broken-client behavior already passed. Afterward, all
  3 server tests plus the dashboard reconnect-hook test passed.
- `./scripts/check.sh` was run after every completed outcome. The final suite at
  the end of functional work compiled the project and passed 19 tests.
- The normal and chaos simulators were used during diagnosis; chaos mode visibly
  reproduced cross-boot sequence collisions in the starter behavior.
- Final normal and chaos runs against the merged fixes succeeded. New boots and
  increasing sequences advanced state; explicit duplicates reported no change;
  delayed lower sequences were retained without replacing current state;
  skewed clocks did not block higher sequences; and a restarted device's
  sequence 1 was accepted under its newer generation.
- Browser smoke checks confirmed the dashboard loaded, WebSocket status became
  connected, live simulator values rendered, and an authoritative state
  committed while the server was offline appeared after snapshot reload.

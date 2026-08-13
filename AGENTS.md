# Agent instructions

This repository implements a local environmental telemetry gateway. Before changing behavior, read these normative documents in full:

- `docs/protocol.md`
- `docs/runtime-contract.md`
- `docs/api.md`

If code, tests, or this file conflict with those documents, the documents take precedence.

## Core invariants

- A device creates a new opaque `bootId` on every process start. Never infer ordering from the text of a `bootId`.
- Boot registration is idempotent for `(deviceId, bootId)`. A repeated registration returns the original server-assigned generation with `created: false`.
- Generations increase monotonically per device. Every newly accepted boot has a generation greater than all earlier boots for that device.
- Reject telemetry for an unregistered boot with HTTP `409` and `{"error": "unknown_boot"}`.
- The transport is at-least-once and events may arrive late, duplicated, or out of order.
- Logical event identity is `(deviceId, bootId, sequence)`. Raw audit history contains at most one row per logical event.
- A duplicate telemetry request succeeds with `duplicate: true`, does not change current state, and does not publish a realtime state-change message.
- Preserve raw telemetry audit history. Stale valid events still belong in history.
- Current state is stored per `(deviceId, metric)`.
- Compare current-state candidates by `(generation, sequence)`, in that order. Higher is newer.
- `deviceTime` is diagnostic metadata only and must never determine current-state ordering.

## Transaction and realtime rules

- SQLite is the source of truth; WebSocket messages are best-effort notifications.
- For telemetry ingestion: validate, complete the database transaction, determine whether authoritative current state changed, then publish.
- Publish only after a successful commit and only when current state changed.
- A failed transaction, duplicate event, or stale event must not produce a state-change message.
- Isolate WebSocket clients so one slow or broken client cannot block healthy clients.
- Bound memory used for every client. Close or drop a client when its configured buffer is exceeded.
- The dashboard needs current state, not every raw event.
- The dashboard must fetch `GET /api/devices` at startup and after every successful WebSocket reconnection, then treat realtime messages as updates to that snapshot.

## API compatibility

- `POST /api/boots` registers a boot and returns `deviceId`, `bootId`, `generation`, and `created`.
- `POST /api/telemetry` returns `accepted`, `duplicate`, and `currentChanged`.
- `GET /api/devices` returns authoritative current state.
- `GET /api/events?limit=100` returns raw events newest-received first.
- `ws://127.0.0.1:3000/ws` publishes `device.state.changed` messages whose `data` matches the state fields documented in `docs/api.md`.
- `GET /health/live` reports process liveness and must not depend on the database.
- `GET /health/ready` reports whether database-backed work is available and may return a non-200 response when it is not.
- Keep existing API behavior compatible unless a necessary change is documented.

## Engineering constraints

- Keep all runtime components on the local machine.
- Do not add cloud services, hosted databases, remote queues, paid APIs, or paid dependencies.
- Do not replace the application or framework.
- Do not delete the local database on startup or use database deletion as a repair strategy.
- Use versioned, data-preserving migrations for schema changes.
- Add focused tests for every behavior changed, especially duplicates, restarts, message reordering, clock skew, transaction failure, slow clients, and reconnect recovery.
- Run `./scripts/check.sh` before considering a change complete.

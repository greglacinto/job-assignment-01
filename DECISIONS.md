# Engineering decisions

## Invariants identified

- A boot is identified by `(deviceId, bootId)`. Registering it repeatedly is
  idempotent, while each newly accepted boot receives a higher server-assigned
  generation for that device.
- A logical telemetry event is identified by `(deviceId, bootId, sequence)`.
  The raw audit history contains at most one row for that identity.
- Current state is authoritative per `(deviceId, metric)` and is ordered by
  `(generation, sequence)`. `deviceTime` is diagnostic metadata only.
- Unique but stale events remain in raw history without changing current state.
- The database is the source of truth. Realtime publication happens only after
  a successful transaction and only when authoritative current state changed.
- WebSocket delivery is best effort. Clients are isolated, their buffers are
  bounded, and the dashboard recovers truth from a snapshot after connecting.

## Incidents fixed

- Sequence reuse after a device restart was incorrectly classified as a
  duplicate because the audit table omitted `boot_id` from its unique key.
- Delayed events and skewed device clocks could move current state backward or
  prevent a valid later sequence from advancing it.
- A candidate state was published before database ingestion, allowing
  duplicates, stale events, and failed transactions to produce false updates.
- Realtime publication awaited clients sequentially, so one blocked client
  could stall healthy clients indefinitely.
- Client memory was not explicitly bounded, and the dashboard did not reload
  authoritative state after a WebSocket reconnection.

## Design choices and trade-offs

- Migration 002 rebuilds `telemetry_events` with the correct composite unique
  key, copies every existing row with its original ID, then recreates the
  received-time index. Rebuilding is the portable SQLite way to replace a
  table-level unique constraint; it briefly requires space for both tables.
- The current-state upsert compares generation first and sequence second in
  SQL. This keeps the ordering decision atomic with the audit insert and state
  update.
- `TelemetryService` publishes from the committed `IngestResult`, rather than
  from a pre-transaction preview. A notification can still be missed if the
  process stops after commit, which is acceptable because WebSockets are not a
  replay channel and the dashboard reloads the database snapshot.
- Each WebSocket client has one sender task and a bounded queue of 32 messages.
  Publication only enqueues. A full queue removes the client, cancels its
  sender, and closes it with code 1013. This favors healthy clients and bounded
  memory over delivery of every intermediate state.
- The dashboard requests a snapshot after every successful connection and
  buffers realtime messages while snapshot requests are active so a completed
  request cannot overwrite a newer notification.

## Schema or API compatibility concerns

- Migration 002 is data preserving and applies automatically to existing
  version-1 databases. New databases apply migration 001 followed by 002.
- The HTTP request and response shapes, status codes, WebSocket message shape,
  and raw-event ordering remain unchanged.
- No cloud service, remote queue, hosted database, paid dependency, or database
  deletion was introduced.

## Remaining risks or incomplete work

- WebSocket messages are intentionally not replayed. A client can miss updates
  while disconnected, but reconnect snapshot recovery restores current state.
- Slow-client isolation and buffer overflow are covered with deterministic
  unit tests, not a sustained-load benchmark.
- The repository has no JavaScript test runner. Reconnect snapshot invocation
  is guarded by an asset-level test and the dashboard was browser smoke tested;
  automatic reconnect timing is not exercised end to end in CI.
- The design remains a single-process, local SQLite application, as required.
  It is not intended to coordinate multiple gateway processes.
- No known required behavior remains incomplete.

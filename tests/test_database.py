import sqlite3

from telemetry_gateway.database import TelemetryStore
from telemetry_gateway.migrations import migration_001
from telemetry_gateway.models import BootRegistrationInput, TelemetryInput


def telemetry(**overrides) -> TelemetryInput:
    values = {
        "deviceId": "device-01",
        "bootId": "boot-a",
        "sequence": 1,
        "deviceTime": "2026-08-12T09:00:00+00:00",
        "metric": "temperature",
        "value": 21.4,
    }
    values.update(overrides)
    return TelemetryInput.model_validate(values)


def test_registers_a_boot_idempotently() -> None:
    store = TelemetryStore(":memory:")
    try:
        event = BootRegistrationInput(deviceId="device-01", bootId="boot-a")

        first = store.register_boot(event)
        second = store.register_boot(event)

        assert first.to_api() == {
            "deviceId": "device-01",
            "bootId": "boot-a",
            "generation": 1,
            "created": True,
        }
        assert second.to_api() == {
            "deviceId": "device-01",
            "bootId": "boot-a",
            "generation": 1,
            "created": False,
        }
    finally:
        store.close()


def test_stores_a_basic_event_and_calculates_current_state() -> None:
    store = TelemetryStore(":memory:")
    try:
        store.register_boot(BootRegistrationInput(deviceId="device-01", bootId="boot-a"))

        result = store.ingest(telemetry(), "2026-08-12T09:00:01+00:00")

        assert result.duplicate is False
        assert result.current_changed is True
        assert store.list_current_states()[0].to_api() == {
            "deviceId": "device-01",
            "bootId": "boot-a",
            "generation": 1,
            "sequence": 1,
            "deviceTime": "2026-08-12T09:00:00+00:00",
            "receivedAt": "2026-08-12T09:00:01+00:00",
            "metric": "temperature",
            "value": 21.4,
        }
        assert len(store.list_events(10)) == 1
    finally:
        store.close()


def test_repeated_event_from_same_boot_is_a_duplicate() -> None:
    store = TelemetryStore(":memory:")
    try:
        store.register_boot(BootRegistrationInput(deviceId="device-01", bootId="boot-a"))
        store.ingest(telemetry(), "2026-08-12T09:00:01+00:00")

        duplicate = store.ingest(telemetry(), "2026-08-12T09:00:02+00:00")

        assert duplicate.to_api() == {
            "accepted": True,
            "duplicate": True,
            "currentChanged": False,
        }
        assert len(store.list_events(10)) == 1
    finally:
        store.close()


def test_same_sequence_from_different_boots_is_a_distinct_event() -> None:
    store = TelemetryStore(":memory:")
    try:
        store.register_boot(BootRegistrationInput(deviceId="device-01", bootId="boot-a"))
        store.register_boot(BootRegistrationInput(deviceId="device-01", bootId="boot-b"))
        store.ingest(telemetry(), "2026-08-12T09:00:01+00:00")

        restarted = store.ingest(
            telemetry(
                bootId="boot-b",
                deviceTime="2026-08-12T09:01:00+00:00",
                value=22.0,
            ),
            "2026-08-12T09:01:01+00:00",
        )

        assert restarted.duplicate is False
        assert len(store.list_events(10)) == 2
    finally:
        store.close()


def test_event_identity_migration_preserves_existing_audit_rows(tmp_path) -> None:
    database_path = tmp_path / "gateway.db"
    connection = sqlite3.connect(database_path)
    migration_001(connection)
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (1, datetime('now'))"
    )
    connection.execute(
        "INSERT INTO device_boots VALUES ('device-01', 'boot-a', 1, datetime('now'))"
    )
    connection.execute(
        """
        INSERT INTO telemetry_events
            (device_id, boot_id, generation, sequence, device_time,
             received_at, metric, value)
        VALUES ('device-01', 'boot-a', 1, 1, '2026-08-12T09:00:00+00:00',
                '2026-08-12T09:00:01+00:00', 'temperature', 21.4)
        """
    )
    connection.commit()
    connection.close()

    store = TelemetryStore(str(database_path))
    try:
        store.register_boot(BootRegistrationInput(deviceId="device-01", bootId="boot-b"))
        restarted = store.ingest(
            telemetry(
                bootId="boot-b",
                deviceTime="2026-08-12T09:01:00+00:00",
                value=22.0,
            ),
            "2026-08-12T09:01:01+00:00",
        )

        assert restarted.duplicate is False
        events = store.list_events(10)
        assert [(event.state.boot_id, event.state.sequence) for event in events] == [
            ("boot-b", 1),
            ("boot-a", 1),
        ]
    finally:
        store.close()


def test_delayed_lower_sequence_does_not_move_current_state_backward() -> None:
    store = TelemetryStore(":memory:")
    try:
        store.register_boot(BootRegistrationInput(deviceId="device-01", bootId="boot-a"))
        store.ingest(
            telemetry(
                sequence=2,
                deviceTime="2026-08-12T09:00:00+00:00",
                value=22.0,
            ),
            "2026-08-12T09:00:01+00:00",
        )

        delayed = store.ingest(
            telemetry(
                sequence=1,
                deviceTime="2026-08-13T09:00:00+00:00",
                value=21.0,
            ),
            "2026-08-12T09:00:02+00:00",
        )

        assert delayed.duplicate is False
        assert delayed.current_changed is False
        assert len(store.list_events(10)) == 2
        current = store.list_current_states()[0]
        assert current.sequence == 2
        assert current.value == 22.0
    finally:
        store.close()


def test_higher_sequence_advances_state_despite_earlier_device_clock() -> None:
    store = TelemetryStore(":memory:")
    try:
        store.register_boot(BootRegistrationInput(deviceId="device-01", bootId="boot-a"))
        store.ingest(
            telemetry(
                sequence=1,
                deviceTime="2026-08-13T09:00:00+00:00",
                value=21.0,
            ),
            "2026-08-12T09:00:01+00:00",
        )

        next_event = store.ingest(
            telemetry(
                sequence=2,
                deviceTime="2026-08-12T09:00:00+00:00",
                value=22.0,
            ),
            "2026-08-12T09:00:02+00:00",
        )

        assert next_event.current_changed is True
        current = store.list_current_states()[0]
        assert current.sequence == 2
        assert current.value == 22.0
    finally:
        store.close()


def test_older_boot_does_not_replace_state_from_newer_generation() -> None:
    store = TelemetryStore(":memory:")
    try:
        store.register_boot(BootRegistrationInput(deviceId="device-01", bootId="boot-a"))
        store.register_boot(BootRegistrationInput(deviceId="device-01", bootId="boot-b"))
        store.ingest(
            telemetry(
                bootId="boot-b",
                deviceTime="2026-08-12T09:00:00+00:00",
                value=22.0,
            ),
            "2026-08-12T09:00:01+00:00",
        )

        older_boot = store.ingest(
            telemetry(
                bootId="boot-a",
                sequence=99,
                deviceTime="2026-08-13T09:00:00+00:00",
                value=99.0,
            ),
            "2026-08-12T09:00:02+00:00",
        )

        assert older_boot.duplicate is False
        assert older_boot.current_changed is False
        assert len(store.list_events(10)) == 2
        current = store.list_current_states()[0]
        assert current.boot_id == "boot-b"
        assert current.generation == 2
        assert current.value == 22.0
    finally:
        store.close()

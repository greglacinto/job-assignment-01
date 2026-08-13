import asyncio
from datetime import datetime, timezone

import pytest

from telemetry_gateway.models import (
    BootRegistrationResult,
    DeviceState,
    IngestResult,
    TelemetryInput,
)
from telemetry_gateway.service import TelemetryService


class FakeRepository:
    def __init__(
        self,
        state: DeviceState,
        operations: list[str],
        result: IngestResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.state = state
        self.operations = operations
        self.result = result or IngestResult(False, True, state)
        self.error = error

    def register_boot(self, _event):
        return BootRegistrationResult("device-01", "boot-a", 1, True)

    def preview_state(self, _event, _received_at):
        return self.state

    def ingest(self, _event, _received_at):
        self.operations.append("ingest")
        if self.error is not None:
            raise self.error
        return self.result

    def list_current_states(self):
        return []

    def list_events(self, _limit):
        return []

    def ping(self):
        return True


class RecordingPublisher:
    def __init__(self, operations: list[str]) -> None:
        self.operations = operations
        self.states: list[DeviceState] = []

    async def publish(self, state: DeviceState) -> None:
        self.operations.append("publish")
        self.states.append(state)


def test_service_publishes_changed_state_after_successful_ingestion() -> None:
    event, state = event_and_state()
    operations: list[str] = []
    repository = FakeRepository(state, operations)
    publisher = RecordingPublisher(operations)
    service = TelemetryService(repository, publisher, now=fixed_now)

    result = asyncio.run(service.ingest(event))

    assert result.current_changed is True
    assert publisher.states == [state]
    assert operations == ["ingest", "publish"]


def test_service_does_not_publish_a_duplicate() -> None:
    event, state = event_and_state()
    operations: list[str] = []
    repository = FakeRepository(
        state,
        operations,
        result=IngestResult(duplicate=True, current_changed=False),
    )
    publisher = RecordingPublisher(operations)
    service = TelemetryService(repository, publisher, now=fixed_now)

    result = asyncio.run(service.ingest(event))

    assert result.to_api() == {
        "accepted": True,
        "duplicate": True,
        "currentChanged": False,
    }
    assert publisher.states == []
    assert operations == ["ingest"]


def test_service_does_not_publish_a_stale_unique_event() -> None:
    event, state = event_and_state()
    operations: list[str] = []
    repository = FakeRepository(
        state,
        operations,
        result=IngestResult(duplicate=False, current_changed=False),
    )
    publisher = RecordingPublisher(operations)
    service = TelemetryService(repository, publisher, now=fixed_now)

    result = asyncio.run(service.ingest(event))

    assert result.to_api() == {
        "accepted": True,
        "duplicate": False,
        "currentChanged": False,
    }
    assert publisher.states == []
    assert operations == ["ingest"]


def test_service_does_not_publish_when_transaction_fails() -> None:
    event, state = event_and_state()
    operations: list[str] = []
    repository = FakeRepository(
        state,
        operations,
        error=RuntimeError("database unavailable"),
    )
    publisher = RecordingPublisher(operations)
    service = TelemetryService(repository, publisher, now=fixed_now)

    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(service.ingest(event))

    assert publisher.states == []
    assert operations == ["ingest"]


def fixed_now() -> datetime:
    return datetime(2026, 8, 12, 9, 0, 1, tzinfo=timezone.utc)


def event_and_state() -> tuple[TelemetryInput, DeviceState]:
    event = TelemetryInput.model_validate(
        {
            "deviceId": "device-01",
            "bootId": "boot-a",
            "sequence": 1,
            "deviceTime": "2026-08-12T09:00:00Z",
            "metric": "temperature",
            "value": 21.4,
        }
    )
    state = DeviceState(
        device_id="device-01",
        boot_id="boot-a",
        generation=1,
        sequence=1,
        device_time="2026-08-12T09:00:00+00:00",
        received_at="2026-08-12T09:00:01+00:00",
        metric="temperature",
        value=21.4,
    )
    return event, state

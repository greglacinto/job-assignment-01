import asyncio

from telemetry_gateway.models import DeviceState
from telemetry_gateway.realtime import RealtimeHub


class FakeWebSocket:
    def __init__(self, *, block_send: bool = False, fail_send: bool = False) -> None:
        self.block_send = block_send
        self.fail_send = fail_send
        self.accepted = False
        self.close_code: int | None = None
        self.messages: list[dict] = []
        self.send_started = asyncio.Event()
        self.message_received = asyncio.Event()
        self.closed = asyncio.Event()
        self.release_send = asyncio.Event()

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        self.send_started.set()
        if self.block_send:
            await self.release_send.wait()
        if self.fail_send:
            raise RuntimeError("client disconnected")
        self.messages.append(message)
        self.message_received.set()

    async def close(self, code: int = 1000) -> None:
        self.close_code = code
        self.closed.set()


def state(sequence: int = 1) -> DeviceState:
    return DeviceState(
        device_id="device-01",
        boot_id="boot-a",
        generation=1,
        sequence=sequence,
        device_time="2026-08-12T09:00:00+00:00",
        received_at="2026-08-12T09:00:01+00:00",
        metric="temperature",
        value=21.4,
    )


def test_slow_client_does_not_block_publish_or_healthy_client() -> None:
    async def scenario() -> None:
        hub = RealtimeHub()
        slow = FakeWebSocket(block_send=True)
        healthy = FakeWebSocket()
        await hub.connect(slow)  # type: ignore[arg-type]
        await hub.connect(healthy)  # type: ignore[arg-type]

        try:
            await asyncio.wait_for(hub.publish(state()), timeout=0.5)
            await asyncio.wait_for(healthy.message_received.wait(), timeout=0.5)

            assert healthy.messages == [
                {"type": "device.state.changed", "data": state().to_api()}
            ]
        finally:
            slow.release_send.set()
            hub.disconnect(slow)  # type: ignore[arg-type]
            hub.disconnect(healthy)  # type: ignore[arg-type]

    asyncio.run(scenario())


def test_buffer_overflow_drops_and_closes_slow_client() -> None:
    async def scenario() -> None:
        hub = RealtimeHub(buffer_limit=1)
        slow = FakeWebSocket(block_send=True)
        await hub.connect(slow)  # type: ignore[arg-type]

        try:
            await hub.publish(state(sequence=1))
            await asyncio.wait_for(slow.send_started.wait(), timeout=0.5)
            await hub.publish(state(sequence=2))
            await hub.publish(state(sequence=3))
            await asyncio.wait_for(slow.closed.wait(), timeout=0.5)

            assert hub.size == 0
            assert slow.close_code == 1013
        finally:
            slow.release_send.set()
            hub.disconnect(slow)  # type: ignore[arg-type]

    asyncio.run(scenario())


def test_broken_client_is_removed_without_affecting_healthy_client() -> None:
    async def scenario() -> None:
        hub = RealtimeHub()
        broken = FakeWebSocket(fail_send=True)
        healthy = FakeWebSocket()
        await hub.connect(broken)  # type: ignore[arg-type]
        await hub.connect(healthy)  # type: ignore[arg-type]

        try:
            await hub.publish(state())
            await asyncio.wait_for(healthy.message_received.wait(), timeout=0.5)
            await asyncio.wait_for(wait_for_size(hub, 1), timeout=0.5)

            assert healthy.messages == [
                {"type": "device.state.changed", "data": state().to_api()}
            ]
        finally:
            hub.disconnect(broken)  # type: ignore[arg-type]
            hub.disconnect(healthy)  # type: ignore[arg-type]

    asyncio.run(scenario())


async def wait_for_size(hub: RealtimeHub, expected: int) -> None:
    while hub.size != expected:
        await asyncio.sleep(0)

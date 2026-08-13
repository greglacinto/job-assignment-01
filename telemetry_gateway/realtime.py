from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import WebSocket

from telemetry_gateway.models import DeviceState


class StatePublisher(Protocol):
    async def publish(self, state: DeviceState) -> None: ...


@dataclass(frozen=True, slots=True)
class ClientSession:
    queue: asyncio.Queue[dict[str, Any]]
    sender: asyncio.Task[None]


class RealtimeHub:
    def __init__(self, buffer_limit: int = 32) -> None:
        if buffer_limit < 1:
            raise ValueError("buffer_limit must be at least 1")
        self._buffer_limit = buffer_limit
        self._clients: dict[WebSocket, ClientSession] = {}
        self._closing_tasks: set[asyncio.Task[None]] = set()

    async def connect(self, client: WebSocket) -> None:
        await client.accept()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self._buffer_limit
        )
        sender = asyncio.create_task(self._send_messages(client, queue))
        self._clients[client] = ClientSession(queue=queue, sender=sender)

    def disconnect(self, client: WebSocket) -> None:
        session = self._clients.pop(client, None)
        if session is not None and session.sender is not asyncio.current_task():
            session.sender.cancel()

    async def publish(self, state: DeviceState) -> None:
        message = {"type": "device.state.changed", "data": state.to_api()}
        for client, session in tuple(self._clients.items()):
            try:
                session.queue.put_nowait(message)
            except asyncio.QueueFull:
                self.disconnect(client)
                self._schedule_close(client)

    async def _send_messages(
        self,
        client: WebSocket,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        try:
            while True:
                await client.send_json(await queue.get())
        except asyncio.CancelledError:
            raise
        except Exception:
            self.disconnect(client)

    def _schedule_close(self, client: WebSocket) -> None:
        task = asyncio.create_task(self._close(client))
        self._closing_tasks.add(task)
        task.add_done_callback(self._closing_tasks.discard)

    @staticmethod
    async def _close(client: WebSocket) -> None:
        try:
            await client.close(code=1013)
        except Exception:
            pass

    @property
    def size(self) -> int:
        return len(self._clients)

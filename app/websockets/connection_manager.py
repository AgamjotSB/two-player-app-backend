import asyncio
import contextlib

import redis.asyncio as redis
from fastapi import WebSocket
from redis.asyncio.client import PubSub


def game_channel(game_id: str) -> str:
    return f"game:{game_id}:channel"


class GameConnection:
    """Wraps one authenticated websocket connection, and a background
    task that listens on this game's Redis channel and forwards every
    message to this socket."""

    def __init__(self, websocket: WebSocket, redis_client: redis.Redis, game_id: str):
        self.websocket = websocket
        self.redis = redis_client
        self.channel = game_channel(game_id)
        self._pubsub: PubSub | None = None
        self._listener_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._pubsub = self.redis.pubsub()
        await self._pubsub.subscribe(self.channel)
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        assert self._pubsub is not None
        try:
            async for message in self._pubsub.listen():
                # subscribe() emits a "subscribe" confirmation event on
                # this stream. Only "message" events are real broadcasts
                if message["type"] != "message":
                    continue
                await self.websocket.send_text(message["data"])
        except asyncio.CancelledError:
            # re-raise so asyncio knows this task was actually cancelled
            # and didn't finish normally. Swallowing might make stop()
            # hang or misbehave
            raise
        except Exception:
            # socket likely already closed on the client side; stop()
            # (called from the disconnect path) will clean up the rest
            pass

    async def stop(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task

        if self._pubsub is not None:
            await self._pubsub.unsubscribe(self.channel)
            await self._pubsub.aclose()


class ConnectionManager:
    """Tracks the one active local connection per (game_id, user_id), so a
    duplicate connection (e.g. a page refresh) evicts the stale one, instead
    of both existing at once."""

    def __init__(self):
        self._connections: dict[tuple[str, str], GameConnection] = {}

    async def connect(self, game_id: str, user_id: str, conn: GameConnection):
        key = (game_id, user_id)
        existing = self._connections.get(key)
        if existing is not None:
            await existing.stop()
            with contextlib.suppress(Exception):
                await existing.websocket.close(code=1000)

        self._connections[key] = conn
        await conn.start()

    async def disconnect(self, game_id: str, user_id: str):
        key = (game_id, user_id)
        conn = self._connections.pop(key, None)
        if conn is not None:
            await conn.stop()

    async def disconnect_all(self):
        for key in list(self._connections.keys()):
            conn = self._connections.pop(key)
            await conn.stop()


manager = ConnectionManager()

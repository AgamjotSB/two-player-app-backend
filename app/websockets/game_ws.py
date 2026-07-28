import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import redis.asyncio as redis
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.security import decode_access_token
from app.config import Config
from app.database import async_session_maker
from app.engines.base import GameEngineError
from app.engines.sudoku import SudokuEngine
from app.models.game import Game, GameStatus
from app.models.user import User
from app.redis_client import get_redis
from app.websockets.connection_manager import GameConnection, game_channel, manager

router = APIRouter()


class HandshakeError(Exception):
    """Any failure during the auth/membership handshake closes
    the socket with the caller."""


class ClientDisconnected(Exception):
    """Client closed the connection before completing handshake.
    Nothing to clean up, nothing to close."""


@dataclass
class WSContext:
    """Bundles everything a per-message handler needs."""

    websocket: WebSocket
    redis_client: redis.Redis
    engine: SudokuEngine
    game_id: uuid.UUID
    game_id_str: str
    user_id_str: str


async def _handshake(websocket: WebSocket, game_id: uuid.UUID) -> tuple[User, Game]:
    try:
        raw = await asyncio.wait_for(
            websocket.receive_json(), timeout=Config.ws_auth_timeout_seconds
        )

    except asyncio.TimeoutError as e:
        raise HandshakeError("timed out waiting for auth message") from e
    except WebSocketDisconnect as e:
        raise ClientDisconnected() from e
    except ValueError as e:
        raise HandshakeError("malformed auth message") from e

    if raw.get("action") != "auth" or not raw.get("token"):
        raise HandshakeError("first message must be {'action': 'auth', 'token': ...}")

    user_id = decode_access_token(raw["token"])
    if user_id is None:
        raise HandshakeError("invalid or expired token")

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HandshakeError("user not found")

        result = await session.execute(select(Game).where(Game.game_id == game_id))
        game = result.scalar_one_or_none()
        if game is None:
            raise HandshakeError("game not found")

        if game.status not in (GameStatus.WAITING, GameStatus.ACTIVE):
            raise HandshakeError("game is not connectable in its current state")

        if user_id not in (game.player_1_id, game.player_2_id):
            raise HandshakeError("not a player in this game")

    return user, game


async def _handle_move(ctx: WSContext, raw: dict) -> None:
    try:
        payload, sender_is_behind = await ctx.engine.process_move(ctx.user_id_str, raw)
    except GameEngineError as e:
        await ctx.websocket.send_json({"type": "error", "detail": str(e)})
        return

    await ctx.redis_client.publish(game_channel(ctx.game_id_str), json.dumps(payload))

    if sender_is_behind:
        try:
            state = await ctx.engine.sync_state()
            await ctx.websocket.send_json(state)  # update stale state of sender
        except GameEngineError:
            pass

    if await ctx.engine.check_win_condition():
        await _complete_game(ctx.game_id)
        await ctx.redis_client.publish(
            game_channel(ctx.game_id_str),
            json.dumps({"type": "game_over", "sequence": payload["sequence"]}),
        )


async def _handle_toggle_candidate(ctx: WSContext, raw: dict) -> None:
    try:
        payload, sender_is_behind = await ctx.engine.toggle_candidate(
            ctx.user_id_str, raw
        )
    except GameEngineError as e:
        await ctx.websocket.send_json({"type": "error", "detail": str(e)})
        return

    await ctx.redis_client.publish(game_channel(ctx.game_id_str), json.dumps(payload))

    if sender_is_behind:
        try:
            state = await ctx.engine.sync_state()
            await ctx.websocket.send_json(state)
        except GameEngineError:
            pass


async def _handle_unknown_action(ctx: WSContext, raw: dict) -> None:
    await ctx.websocket.send_json({"type": "error", "detail": "unknown action"})


@router.websocket("/game/{game_id}")
async def websocket_game_endpoint(
    websocket: WebSocket,
    game_id: uuid.UUID,
    redis_client: redis.Redis = Depends(get_redis),
):
    await websocket.accept()
    try:
        user, game = await _handshake(websocket, game_id)
    except ClientDisconnected:
        return
    except HandshakeError as e:
        await websocket.close(code=1008, reason=str(e))
        return

    assert user.user_id is not None
    user_id_str = str(user.user_id)
    game_id_str = str(game_id)

    conn = GameConnection(websocket, redis_client, game_id_str)
    await manager.connect(game_id_str, user_id_str, conn)

    engine = SudokuEngine(game_id_str, redis_client)

    ctx = WSContext(
        websocket=websocket,
        redis_client=redis_client,
        engine=engine,
        game_id=game_id,
        game_id_str=game_id_str,
        user_id_str=user_id_str,
    )

    try:
        # send reconnecting/joining player the current game state
        if game.status == GameStatus.ACTIVE:
            try:
                state = await engine.sync_state()
                await websocket.send_json(state)
            except GameEngineError:
                pass  # game not initialized in redis (p1 connected before p2 joined)

        while True:
            raw = await websocket.receive_json()

            match raw.get("action"):
                case "move":
                    await _handle_move(ctx, raw)
                case "toggle_candidate":
                    await _handle_toggle_candidate(ctx, raw)
                case _:
                    await _handle_unknown_action(ctx, raw)

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(game_id_str, user_id_str)


async def _complete_game(game_id: uuid.UUID):
    async with async_session_maker() as session:
        result = await session.execute(select(Game).where(Game.game_id == game_id))
        game = result.scalar_one_or_none()
        if game is None or game.status == GameStatus.COMPLETED:
            return  # already completed by a near-simultaneous final move
        game.status = GameStatus.COMPLETED
        game.completed_at = datetime.now(timezone.utc)
        session.add(game)
        await session.commit()

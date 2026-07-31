import json
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.auth.dependencies import get_current_user
from app.clients.youdosudoku import fetch_sudoku_puzzle
from app.config import Config
from app.database import get_session
from app.engines.base import GameEngineError
from app.engines.sudoku import SudokuEngine
from app.models.game import Game, GameCreateResponse, GameStatus
from app.models.sudoku import SudokuGame, SudokuGameCreate, SudokuGameState
from app.models.user import User
from app.redis_client import get_redis
from app.websockets.connection_manager import game_channel

router = APIRouter()


@router.post(
    "/sudoku", response_model=GameCreateResponse, status_code=status.HTTP_201_CREATED
)
async def create_sudoku_game(
    data: SudokuGameCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    puzzle, solution = await fetch_sudoku_puzzle(data.difficulty)
    assert current_user.user_id is not None

    game = Game(player_1_id=current_user.user_id, status=GameStatus.WAITING)
    session.add(game)
    await session.flush()

    assert game.game_id is not None
    sudoku_game = SudokuGame(
        game_id=game.game_id,
        initial_state=puzzle,
        solution_state=solution,
        difficulty=data.difficulty,
    )
    session.add(sudoku_game)

    await session.commit()

    invite_url = f"{Config.frontend_url}/game/{game.game_id}"

    return GameCreateResponse(game_id=game.game_id, invite_url=invite_url)


@router.post("/{game_id}/join", response_model=SudokuGameState)
async def join_sudoku_game(
    game_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    redis_client: redis.Redis = Depends(get_redis),
):
    game = await _load_game_or_404(game_id, session)

    is_player_1 = game.player_1_id == current_user.user_id
    is_player_2 = game.player_2_id == current_user.user_id

    if is_player_1 or is_player_2:
        sudoku_game = await _load_sudoku_game_or_404(game_id, session)
        return await _resolve_sudoku_state(game, sudoku_game, redis_client, session)

    if game.player_2_id is None:
        game.player_2_id = current_user.user_id
        game.status = GameStatus.ACTIVE
        session.add(game)
        await session.commit()

        await redis_client.publish(
            game_channel(str(game.game_id)),
            json.dumps(
                {"type": "player_joined", "player_id": str(current_user.user_id)}
            ),
        )

        sudoku_game = await _load_sudoku_game_or_404(game_id, session)

        assert game.game_id is not None
        engine = SudokuEngine(str(game.game_id), redis_client)
        await engine.initialize_game(
            sudoku_game.initial_state, sudoku_game.solution_state
        )

        return await _resolve_sudoku_state(game, sudoku_game, redis_client, session)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This game is not available to join",
    )


@router.get("/{game_id}", response_model=SudokuGameState)
async def get_sudoku_game(
    game_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    redis_client: redis.Redis = Depends(get_redis),
):
    game = await _load_game_or_404(game_id, session)

    if current_user.user_id not in (game.player_1_id, game.player_2_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a player in this game",
        )

    sudoku_game = await _load_sudoku_game_or_404(game_id, session)
    return await _resolve_sudoku_state(game, sudoku_game, redis_client, session)


async def _load_game_or_404(game_id: uuid.UUID, session: AsyncSession) -> Game:
    result = await session.execute(select(Game).where(Game.game_id == game_id))
    game = result.scalar_one_or_none()
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )
    return game


async def _load_sudoku_game_or_404(
    game_id: uuid.UUID, session: AsyncSession
) -> SudokuGame:
    result = await session.execute(
        select(SudokuGame).where(SudokuGame.game_id == game_id)
    )
    sudoku_game = result.scalar_one_or_none()
    if sudoku_game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sudoku game not found"
        )
    return sudoku_game


async def _player_usernames(
    game: Game, session: AsyncSession
) -> tuple[str | None, str | None]:
    ids = [pid for pid in (game.player_1_id, game.player_2_id) if pid is not None]

    if not ids:
        return None, None

    result = await session.execute(
        select(User.user_id, User.username).where(col(User.user_id).in_(ids))
    )
    by_id = {user_id: username for user_id, username in result.all()}
    return by_id.get(game.player_1_id), by_id.get(game.player_2_id)


async def _resolve_sudoku_state(
    game: Game,
    sudoku_game: SudokuGame,
    redis_client: redis.Redis,
    session: AsyncSession,
) -> SudokuGameState:
    usernames = await _player_usernames(game, session)

    if game.status == GameStatus.ACTIVE:
        engine = SudokuEngine(str(game.game_id), redis_client)
        try:
            state = await engine.sync_state()
            return _sudoku_state_from(
                game,
                sudoku_game,
                current_state=state["current"],
                sequence=state["sequence"],
                candidates=state["candidates"],
                usernames=usernames,
            )
        except GameEngineError:
            pass  # Redis missing/expired despite ACTIVE

    if game.status == GameStatus.COMPLETED:
        return _sudoku_state_from(
            game,
            sudoku_game,
            current_state=sudoku_game.solution_state,
            sequence=None,
            candidates={},
            usernames=usernames,
        )

    return _sudoku_state_from(
        game,
        sudoku_game,
        current_state=sudoku_game.initial_state,
        sequence=0,
        candidates={},
        usernames=usernames,
    )


def _sudoku_state_from(
    game: Game,
    sudoku_game: SudokuGame,
    current_state: str,
    sequence: int | None,
    candidates: dict,
    usernames: tuple[str | None, str | None],
) -> SudokuGameState:
    assert game.game_id is not None

    return SudokuGameState(
        game_id=game.game_id,
        status=game.status,
        player_1_id=game.player_1_id,
        player_2_id=game.player_2_id,
        player_1_username=usernames[0],
        player_2_username=usernames[1],
        initial_state=sudoku_game.initial_state,
        current_state=current_state,
        sequence=sequence,
        candidates=candidates,
        difficulty=sudoku_game.difficulty,
    )

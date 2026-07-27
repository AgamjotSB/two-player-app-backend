from typing import Any, Dict

from app.engines.base import BaseGameEngine, GameEngineError
from app.models.sudoku import SudokuMoveData

BOARD_SIZE = 9
NUM_CELLS = BOARD_SIZE * BOARD_SIZE
STATE_TTL_SECONDS = 60 * 60 * 24 * 2  # 2 days


class SudokuEngine(BaseGameEngine):
    def _state_key(self) -> str:
        return f"game:{self.game_id}:state"

    def _board_key(self) -> str:
        return f"game:{self.game_id}:board"

    async def initialize_game(self, initial_state: str, solution_state: str) -> None:
        state_key = self._state_key()
        if await self.redis.exists(state_key):
            return

        await self.redis.hset(
            state_key,
            mapping={
                "initial": initial_state,
                "solution": solution_state,
                "sequence": 0,
            },
        )
        await self.redis.expire(state_key, STATE_TTL_SECONDS)

        board_key = self._board_key()
        await self.redis.hset(
            board_key,
            mapping={str(i): initial_state[i] for i in range(NUM_CELLS)},
        )
        await self.redis.expire(board_key, STATE_TTL_SECONDS)

    async def process_move(
        self, player_id: str, move_data: Dict[str, int]
    ) -> tuple[Dict[str, Any], bool]:
        try:
            move = SudokuMoveData(**move_data)
        except ValueError as e:
            raise GameEngineError(f"malformed move payload: {e}") from e

        state_key = self._state_key()
        initial = await self.redis.hget(state_key, "initial")
        if initial is None:
            raise GameEngineError("game state not initialized")
        assert isinstance(initial, str)

        idx = move.row * BOARD_SIZE + move.col
        if initial[idx] != "0":
            raise GameEngineError("cannot modify a given clue cell")

        await self.redis.hset(self._board_key(), str(idx), str(move.value))

        new_sequence = await self.redis.hincrby(state_key, "sequence", 1)
        prior_sequence = new_sequence - 1

        payload = {
            "type": "move",
            "game_type": "sudoku",
            "player_id": player_id,
            "row": move.row,
            "col": move.col,
            "value": move.value,
            "sequence": new_sequence,
        }

        sender_is_behind = move.last_seen_sequence < prior_sequence
        return payload, sender_is_behind

    async def _current_board_string(self) -> str | None:
        board = await self.redis.hgetall(self._board_key())
        if not board:
            return None
        return "".join(str(board[str(i)]) for i in range(NUM_CELLS))

    async def check_win_condition(self) -> bool:
        solution = await self.redis.hget(self._state_key(), "solution")
        if solution is None:
            return False
        assert isinstance(solution, str)

        current = await self._current_board_string()
        if current is None:
            return False

        return current == solution

    async def sync_state(self) -> Dict[str, Any]:
        state = await self.redis.hgetall(self._state_key())
        if not state:
            raise GameEngineError("game state not initialized")

        current = await self._current_board_string()
        if current is None:
            raise GameEngineError("game state not initialized")

        return {
            "type": "sync_state",
            "game_type": "sudoku",
            "initial": state["initial"],
            "current": current,
            "sequence": int(state["sequence"]),
        }

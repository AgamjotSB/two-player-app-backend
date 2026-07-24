from typing import Any, Dict

from pydantic import BaseModel, Field

from app.engines.base import BaseGameEngine, GameEngineError

BOARD_SIZE = 9
STATE_TTL_SECONDS = 60 * 60 * 24 * 2  # 2 days


class SudokuMoveData(BaseModel):
    row: int = Field(ge=0, le=8)
    col: int = Field(ge=0, le=8)
    value: int = Field(ge=0, le=9)  # 0 clears the cell


class SudokuEngine(BaseGameEngine):
    def _key(self) -> str:
        return f"game:{self.game_id}:state"

    async def initialize_game(self, initial_state: str, solution_state: str) -> None:
        key = self._key()
        if await self.redis.exists(key):
            return

        await self.redis.hset(
            key,
            mapping={
                "initial": initial_state,
                "current": initial_state,
                "solution": solution_state,
                "sequence": 0,
            },
        )

        await self.redis.expire(key, STATE_TTL_SECONDS)

    async def process_move(
        self, player_id: str, move_data: Dict[str, int]
    ) -> Dict[str, Any]:
        try:
            move = SudokuMoveData(**move_data)
        except ValueError as e:
            raise GameEngineError(f"malformed move payload: {e}") from e

        key = self._key()

        initial, current, sequence = await self.redis.hmget(
            key, ["initial", "current", "sequence"]
        )

        if initial is None or current is None or sequence is None:
            raise GameEngineError("game state not initialized")
        assert (
            isinstance(initial, str)
            and isinstance(current, str)
            and isinstance(sequence, str)
        )

        idx = move.row * BOARD_SIZE + move.col
        if initial[idx] != "0":
            raise GameEngineError("cannot modify a given clue cell")

        new_current = current[:idx] + str(move.value) + current[idx + 1 :]
        new_sequence = int(sequence) + 1

        await self.redis.hset(
            key, mapping={"current": new_current, "sequence": new_sequence}
        )

        return {
            "type": "move",
            "game_type": "sudoku",
            "player_id": player_id,
            "row": move.row,
            "col": move.col,
            "value": move.value,
            "sequence": new_sequence,
        }

    async def check_win_condition(self) -> bool:
        current, solution = await self.redis.hmget(self._key(), ["current", "solution"])
        if current is None or solution is None:
            return False
        return current == solution

    async def sync_state(self) -> Dict[str, Any]:
        state = await self.redis.hgetall(self._key())
        if not state:
            raise GameEngineError("game state not initialized")
        return {
            "type": "sync_state",
            "game_type": "sudoku",
            "initial": state["initial"],
            "current": state["current"],
            "sequence": int(state["sequence"]),
        }

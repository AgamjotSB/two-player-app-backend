from typing import Any, Dict

from app.engines.base import BaseGameEngine, GameEngineError
from app.models.sudoku import CandidateToggleData, HighlightCellData, SudokuMoveData

BOARD_SIZE = 9
NUM_CELLS = BOARD_SIZE * BOARD_SIZE
STATE_TTL_SECONDS = 60 * 60 * 24 * 2  # 2 days


class SudokuEngine(BaseGameEngine):
    def _state_key(self) -> str:
        return f"game:{self.game_id}:state"

    def _board_key(self) -> str:
        return f"game:{self.game_id}:board"

    def _candidates_key(self) -> str:
        return f"game:{self.game_id}:candidates"

    @staticmethod
    def _peers(idx: int) -> list[int]:
        """The 20 cells sharing idx's row, column, or 3x3 box (idx itself excluded)."""
        row, col = divmod(idx, BOARD_SIZE)
        box_row, box_col = (row // 3) * 3, (col // 3) * 3

        peer_set: set[int] = set()
        for c in range(BOARD_SIZE):
            peer_set.add(row * BOARD_SIZE + c)
        for r in range(BOARD_SIZE):
            peer_set.add(r * BOARD_SIZE + col)
        for dr in range(3):
            for dc in range(3):
                peer_set.add((box_row + dr) * BOARD_SIZE + (box_col + dc))

        peer_set.discard(idx)
        return sorted(peer_set)

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
        initial = str(initial)

        idx = move.row * BOARD_SIZE + move.col
        if initial[idx] != "0":
            raise GameEngineError("cannot modify a given clue cell")

        await self.redis.hset(self._board_key(), str(idx), str(move.value))

        eliminated = []
        if move.value != 0:
            eliminated = await self._eliminate_candidates(idx, move.value)

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
            "eliminated": eliminated,
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

        candidates_raw = await self.redis.hgetall(self._candidates_key())
        candidates = {k: int(str(v)) for k, v in candidates_raw.items()}

        return {
            "type": "sync_state",
            "game_type": "sudoku",
            "initial": state["initial"],
            "current": current,
            "candidates": candidates,
            "sequence": int(state["sequence"]),
        }

    async def toggle_candidate(self, player_id: str, data: Dict[str, int]):
        try:
            toggle = CandidateToggleData(**data)
        except ValueError as e:
            raise GameEngineError(f"malformed candidate payload: {e}") from e

        idx = toggle.row * BOARD_SIZE + toggle.col
        board_val = await self.redis.hget(self._board_key(), str(idx))
        if board_val is None:
            raise GameEngineError("game state not initialized")
        if str(board_val) != "0":
            raise GameEngineError("cannot mark candidates on a filled cell")

        candidates_key = self._candidates_key()
        bit = 1 << (toggle.digit - 1)

        current_mask_raw = await self.redis.hget(candidates_key, str(idx))
        current_mask = int(str(current_mask_raw)) if current_mask_raw is not None else 0
        new_mask = current_mask ^ bit

        if new_mask == 0:
            await self.redis.hdel(candidates_key, str(idx))
        else:
            await self.redis.hset(candidates_key, str(idx), new_mask)
        await self.redis.expire(candidates_key, STATE_TTL_SECONDS)

        new_sequence = await self.redis.hincrby(self._state_key(), "sequence", 1)
        prior_sequence = new_sequence - 1
        active_digits = [d + 1 for d in range(9) if new_mask & (1 << d)]

        payload = {
            "type": "candidate_toggled",
            "player_id": player_id,
            "row": toggle.row,
            "col": toggle.col,
            "candidates": active_digits,
            "sequence": new_sequence,
        }

        sender_is_behind = toggle.last_seen_sequence < prior_sequence
        return payload, sender_is_behind

    async def build_highlight_payload(
        self, player_id: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            highlight = HighlightCellData(**data)
        except ValueError as e:
            raise GameEngineError(f"malformed highlight payload: {e}") from e

        return {
            "type": "cell_highlighted",
            "player_id": player_id,
            "row": highlight.row,
            "col": highlight.col,
        }

    async def _eliminate_candidates(self, idx: int, digit: int) -> list[Dict]:
        candidates_key = self._candidates_key()

        await self.redis.hdel(candidates_key, str(idx))

        peers = self._peers(idx)
        bit = 1 << (digit - 1)
        masks = await self.redis.hmget(candidates_key, [str(p) for p in peers])

        eliminated: list[Dict[str, int]] = []
        to_update = {}
        to_delete: list[str] = []

        for p, m in zip(peers, masks):
            if m is None:
                continue
            m_int = int(str(m))
            if not (m_int & bit):
                continue
            new_mask = m_int & ~bit
            if new_mask == 0:
                to_delete.append(str(p))
            else:
                to_update[str(p)] = new_mask
            eliminated.append(
                {"row": p // BOARD_SIZE, "col": p % BOARD_SIZE, "digit": digit}
            )
        if to_update:
            await self.redis.hset(candidates_key, mapping=to_update)
        if to_delete:
            await self.redis.hdel(candidates_key, *to_delete)

        return eliminated

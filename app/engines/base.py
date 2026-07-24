from abc import ABC, abstractmethod
from typing import Any, Dict

import redis.asyncio as redis


class GameEngineError(Exception):
    """Raised when a move or action is invalid and should be rejected
    (sent back to the sender only, never broadcast)."""


class BaseGameEngine(ABC):
    def __init__(self, game_id: str, redis_client: redis.Redis):
        self.game_id = game_id
        self.redis = redis_client

    @abstractmethod
    async def process_move(
        self, player_id: str, move_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validates a move, updates Redis, and returns the broadcast payload.
        Raises GameEngineError if the move is illegal."""

    @abstractmethod
    async def check_win_condition(self) -> bool:
        """Checks if the puzzle is solved based on current Redis state."""

    @abstractmethod
    async def sync_state(self) -> Dict[str, Any]:
        """Returns full state for a reconnecting/joining player."""

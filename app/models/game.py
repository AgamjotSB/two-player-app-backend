import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.sudoku import SudokuGame
    from app.models.user import User


class GameType(str, Enum):
    SUDOKU = "sudoku"
    WORDLE = "wordle"


class GameStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class Game(SQLModel, table=True):
    __tablename__ = "game"

    game_id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    game_type: GameType = Field(default=GameType.SUDOKU)

    player_1_id: uuid.UUID = Field(foreign_key="user.user_id")
    player_2_id: uuid.UUID | None = Field(default=None, foreign_key="user.user_id")

    status: GameStatus = Field(default=GameStatus.ACTIVE)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = Field(default=None)

    player_1: User = Relationship(
        back_populates="games_as_p1",
        sa_relationship_kwargs={"foreign_keys": "Game.player_1_id"},
    )
    player_2: User | None = Relationship(
        back_populates="games_as_p2",
        sa_relationship_kwargs={"foreign_keys": "Game.player_2_id"},
    )

    sudoku_details: SudokuGame | None = Relationship(
        back_populates="game", sa_relationship_kwargs={"uselist": False}
    )

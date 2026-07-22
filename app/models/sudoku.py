import uuid
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlmodel import Field, Relationship, SQLModel

from app.models.game import GameStatus

if TYPE_CHECKING:
    from app.models.game import Game


class SudokuDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class SudokuGame(SQLModel, table=True):
    __tablename__ = "sudoku_game"

    game_id: uuid.UUID = Field(foreign_key="game.game_id", primary_key=True)

    initial_state: str = Field(min_length=81, max_length=81)
    solution_state: str = Field(min_length=81, max_length=81)
    difficulty: SudokuDifficulty = Field(default=SudokuDifficulty.MEDIUM)

    game: Game = Relationship(back_populates="sudoku_details")


class SudokuGameCreate(BaseModel):
    difficulty: SudokuDifficulty


class SudokuGameState(BaseModel):
    game_id: uuid.UUID
    status: GameStatus
    player_1_id: uuid.UUID
    player_2_id: uuid.UUID | None
    initial_state: str
    difficulty: SudokuDifficulty

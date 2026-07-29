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
    current_state: str
    sequence: int | None
    candidates: dict[str, int]
    difficulty: SudokuDifficulty


class SudokuMoveData(BaseModel):
    row: int = Field(ge=0, le=8)
    col: int = Field(ge=0, le=8)
    value: int = Field(ge=0, le=9)  # 0 clears the cell
    last_seen_sequence: int = Field(ge=0)  # sequence client last received from server


class CandidateToggleData(BaseModel):
    row: int = Field(ge=0, le=8)
    col: int = Field(ge=0, le=8)
    digit: int = Field(ge=1, le=9)  # candidates are never 0
    last_seen_sequence: int = Field(ge=0)

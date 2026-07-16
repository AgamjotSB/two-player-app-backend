import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import EmailStr
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.game import Game


class User(SQLModel, table=True):
    __tablename__ = "user"

    user_id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    email: EmailStr = Field(index=True, unique=True, max_length=50)
    username: str = Field(index=True, unique=True, max_length=20)
    password: str = Field(max_length=100)
    display_name: str | None = Field(default=None, max_length=20)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    games_as_p1: list[Game] = Relationship(
        back_populates="player_1",
        sa_relationship_kwargs={"foreign_keys": "Game.player_1_id"},
    )

    games_as_p2: list[Game] = Relationship(
        back_populates="player_2",
        sa_relationship_kwargs={"foreign_keys": "Game.player_2_id"},
    )

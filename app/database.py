from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.config import Config

engine = create_async_engine(
    Config.database_url,
    echo=False,
)


async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with async_session_maker() as session:
        yield session


async def nuke_db():
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO agamjotsb;"
            )
        )


async def init_db():

    # need to import models to autocreate tables
    from app.models import Game, SudokuGame, User

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

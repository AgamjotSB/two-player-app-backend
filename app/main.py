from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients import youdosudoku
from app.config import Config
from app.database import engine, init_db
from app.redis_client import redis_pool
from app.routers import auth, games
from app.websockets import game_ws
from app.websockets.connection_manager import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("DB Initializing")
    await init_db()  # creates tables if missing
    youdosudoku.http_client = httpx.AsyncClient(timeout=5.0)

    yield

    print("Disposing database pools, httpx client")
    await manager.disconnect_all()
    await engine.dispose()  # close postgres pool
    await redis_pool.aclose()  # close redis pool
    await youdosudoku.http_client.aclose()


app = FastAPI(
    title="Two-Player-App",
    description="Websockets and RestAPI for a two player app",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[Config.frontend_url],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(games.router, prefix="/games", tags=["games"])
app.include_router(game_ws.router, prefix="/ws", tags=["websocket"])

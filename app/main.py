from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, init_db
from app.redis_client import redis_pool
from app.routers import auth, games


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("DB Initializing")
    await init_db()  # creates tables if missing

    yield

    print("Server Stopped")
    print("Disposing database pools")
    await engine.dispose()  # close postgres pool
    await redis_pool.aclose()  # close redis pool


app = FastAPI(
    title="Two-Player-App",
    description="Websockets and RestAPI for a two player app",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(games.router, prefix="/games", tags=["games"])

import redis.asyncio as redis

from app.config import Config

redis_pool = redis.from_url(Config.redis_url, decode_responses=True)


async def get_redis():
    yield redis_pool

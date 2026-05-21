import logging
import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger("app.redis")

class RedisClientManager:
    """
    Manages the lifecycle of the async Redis connection.
    Used for sliding window rate-limiting and WebSockets Pub/Sub.
    """
    redis_client: aioredis.Redis = None

    def connect(self):
        """Initialize the Redis client with connection pooling."""
        logger.info(f"Connecting to Redis at {settings.REDIS_URI}")
        self.redis_client = aioredis.from_url(
            settings.REDIS_URI,
            encoding="utf-8",
            decode_responses=True
        )
        logger.info("Redis client connected.")

    async def disconnect(self):
        """Gracefully close Redis connections."""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis client connection closed.")

# Singleton manager
redis_manager = RedisClientManager()

def get_redis() -> aioredis.Redis:
    """Dependency to retrieve the active Redis client."""
    if redis_manager.redis_client is None:
        raise RuntimeError("Redis client is not connected.")
    return redis_manager.redis_client

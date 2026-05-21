import time
from datetime import datetime, timezone
import logging
from fastapi import APIRouter, Depends, status, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.database import get_db
from app.redis_client import get_redis
import redis.asyncio as aioredis

logger = logging.getLogger("app.health")
router = APIRouter()

@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check(
    db: AsyncIOMotorDatabase = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis)
):
    """
    Production-grade deep health check.
    Validates database and Redis connectivity before returning a clean 200 OK.
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": {
            "database": "unknown",
            "redis": "unknown"
        }
    }
    
    # 1. Test MongoDB connection
    try:
        # Run a simple ping command in MongoDB
        await db.command("ping")
        health_status["components"]["database"] = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health_status["components"]["database"] = "unhealthy"
        health_status["status"] = "unhealthy"

    # 2. Test Redis connection
    try:
        await redis_client.ping()
        health_status["components"]["redis"] = "healthy"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        health_status["components"]["redis"] = "unhealthy"
        health_status["status"] = "unhealthy"

    if health_status["status"] != "healthy":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_status
        )

    return health_status

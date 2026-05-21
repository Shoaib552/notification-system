import time
import logging
from fastapi import Request, HTTPException, status
from app.redis_client import get_redis

logger = logging.getLogger("app.rate_limiter")

class RateLimiter:
    """
    Sliding window rate limiter using Redis sorted sets (ZSET).
    Ensures precise concurrency control without boundary reset spikes.
    """
    def __init__(self, limit: int = 30, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds

    async def check_rate_limit(self, request: Request):
        """
        FastAPI dependency to enforce rate limits on endpoints.
        Fails with HTTP 429 and provides a Retry-After header if limits are exceeded.
        """
        # Determine unique client identifier (IP Address fallback)
        client_ip = request.client.host if request.client else "unknown"
        redis = get_redis()
        
        # Redis key identifier
        key = f"rate_limit:{request.url.path}:{client_ip}"
        
        current_time = time.time()
        clear_before = current_time - self.window_seconds
        
        # Execute sliding window pipeline atomically
        pipe = redis.pipeline()
        # Remove elements older than window
        pipe.zremrangebyscore(key, "-inf", clear_before)
        # Count elements in sliding window
        pipe.zcard(key)
        # Fetch the oldest element in the current window to compute Retry-After
        pipe.zrange(key, 0, 0, withscores=True)
        
        _, current_count, oldest_range = await pipe.execute()
        
        if current_count >= self.limit:
            # Exceeded rate limit. Compute remaining seconds for Retry-After.
            # Oldest score is the unix timestamp of the oldest request in the window.
            if oldest_range:
                oldest_timestamp = float(oldest_range[0][1])
                retry_after = int(oldest_timestamp + self.window_seconds - current_time)
            else:
                retry_after = self.window_seconds
                
            retry_after = max(1, retry_after)
            
            logger.warning(f"Rate limit exceeded for IP: {client_ip}. Requests: {current_count}/{self.limit}. Retry after {retry_after}s.")
            
            # Raise exception with 429 and Retry-After header
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)}
            )
            
        # Below limit: Add current request and set expiration
        pipe = redis.pipeline()
        pipe.zadd(key, {str(current_time): current_time})
        pipe.expire(key, self.window_seconds)
        await pipe.execute()
        
        # Allow request to proceed

# Instantiate rate limiter instance for comments (30 requests per minute)
comments_rate_limiter = RateLimiter(limit=30, window_seconds=60)

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException, status
from app.rate_limiter import RateLimiter

@pytest.mark.asyncio
async def test_rate_limiter_under_limit():
    """Verify that requests under the limit are allowed to proceed."""
    limiter = RateLimiter(limit=30, window_seconds=60)
    
    # Mock FastAPI Request
    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.url.path = "/comments"
    
    # Mock Redis client and pipeline
    mock_redis = MagicMock()
    mock_pipeline = AsyncMock()
    
    # Return count = 5 requests in current window, oldest timestamp 5s ago
    mock_pipeline.execute.return_value = (None, 5, [("timestamp", 1716298640.0)])
    mock_redis.pipeline.return_value = mock_pipeline
    
    # Patch get_redis dependency to return our mock Redis client
    with patch("app.rate_limiter.get_redis", return_value=mock_redis):
        # Should execute successfully without raising any exceptions
        await limiter.check_rate_limit(mock_request)
        
    assert mock_pipeline.zremrangebyscore.called
    assert mock_pipeline.zcard.called
    assert mock_pipeline.zrange.called

@pytest.mark.asyncio
async def test_rate_limiter_exceeded_raises_429():
    """Verify that exceeding the limit raises HTTP 429 and includes Retry-After header."""
    limiter = RateLimiter(limit=30, window_seconds=60)
    
    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.url.path = "/comments"
    
    mock_redis = MagicMock()
    mock_pipeline = AsyncMock()
    
    # Return count = 30 (limit reached), oldest element score indicates it was 20 seconds ago
    import time
    oldest_score = time.time() - 20 # oldest request occurred 20 seconds ago
    mock_pipeline.execute.return_value = (None, 30, [("element_data", oldest_score)])
    mock_redis.pipeline.return_value = mock_pipeline
    
    with patch("app.rate_limiter.get_redis", return_value=mock_redis):
        with pytest.raises(HTTPException) as exc_info:
            await limiter.check_rate_limit(mock_request)
            
    assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert exc_info.value.detail == "Too many requests. Please try again later."
    
    # Verify Retry-After header is correctly calculated (approx. 60 - 20 = 40 seconds)
    retry_after = int(exc_info.value.headers["Retry-After"])
    assert 35 <= retry_after <= 45

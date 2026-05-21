import logging
from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.database import get_db
from app.schemas import MentionAnalyticsResponse
from app.crud import get_mention_analytics

logger = logging.getLogger("app.routers.analytics")
router = APIRouter()

@router.get(
    "/analytics/mentions",
    response_model=MentionAnalyticsResponse,
    status_code=status.HTTP_200_OK
)
async def fetch_mention_analytics(
    username: str = Query(..., description="The user to retrieve analytics for"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Returns mention analytics for a given user, including the total count of mentions
    and their top mentioners (users who mention them most frequently).
    """
    username = username.lower().strip()
    logger.info(f"Retrieving mention analytics for user @{username}")
    
    total_mentions, top_mentioners = await get_mention_analytics(db, username)
    
    return {
        "username": username,
        "total_mentions": total_mentions,
        "top_mentioners": top_mentioners
    }

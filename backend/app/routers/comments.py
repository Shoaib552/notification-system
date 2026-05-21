import logging
from typing import List
from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.database import get_db
from app.schemas import CommentCreate, CommentResponse
from app.crud import create_comment, get_comments
from app.utils import parse_mentions
from app.worker import deliver_mention_notification
from app.rate_limiter import comments_rate_limiter

logger = logging.getLogger("app.routers.comments")
router = APIRouter()

@router.post(
    "/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(comments_rate_limiter.check_rate_limit)]
)
async def post_comment(
    payload: CommentCreate,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Creates a new comment. Parses any @mentions within the comment text and asynchronously
    enqueues notification delivery jobs in a Celery background queue.
    
    Enforces a strict sliding window rate limit of 30 requests/minute.
    """
    author = payload.author
    text = payload.text
    
    # 1. Save the comment document in MongoDB
    comment_doc = await create_comment(db, author, text)
    comment_id = comment_doc["_id"]
    
    # 2. Extract unique @mentions, ignoring case and self-mentions
    mentioned_users = parse_mentions(text, author=author)
    
    if mentioned_users:
        logger.info(f"Comment {comment_id} has {len(mentioned_users)} mentions: {mentioned_users}. Enqueuing jobs.")
        
        # Access the active HTTP thread correlation ID to pass to the worker
        from app.main import correlation_id_ctx
        active_corr_id = correlation_id_ctx.get()
        
        # 3. Enqueue a background worker task for each mention to handle delivery asynchronously
        for username in mentioned_users:
            deliver_mention_notification.delay(
                username=username,
                comment_id=comment_id,
                author=author,
                comment_text=text,
                correlation_id=active_corr_id
            )
    else:
        logger.info(f"Comment {comment_id} posted with no mentions.")
        
    return comment_doc


@router.get(
    "/comments",
    response_model=List[CommentResponse],
    status_code=status.HTTP_200_OK
)
async def fetch_comments(
    limit: int = Query(50, ge=1, le=100, description="Retrieve last N comments"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Retrieve the list of latest comments from MongoDB.
    """
    return await get_comments(db, limit)


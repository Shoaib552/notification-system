import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

logger = logging.getLogger("app.crud")

# --- Comment CRUD Operations ---

async def create_comment(db: AsyncIOMotorDatabase, author: str, text: str) -> dict:
    """
    Persist a new comment in MongoDB.
    """
    comment_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    comment_doc = {
        "_id": comment_id,
        "author": author.lower().strip(),
        "text": text,
        "created_at": now
    }
    
    await db["comments"].insert_one(comment_doc)
    logger.info(f"Comment {comment_id} persisted by author @{author}.")
    return comment_doc


async def get_comments(db: AsyncIOMotorDatabase, limit: int = 50) -> List[dict]:
    """
    Retrieve the last N comments from MongoDB, sorted by creation date descending.
    """
    cursor = db["comments"].find().sort([("created_at", DESCENDING)]).limit(limit)
    return await cursor.to_list(length=limit)



# --- Notification CRUD Operations ---

async def get_notifications(
    db: AsyncIOMotorDatabase,
    username: str,
    page: int = 1,
    page_size: int = 20,
    unread_only: bool = False,
    sort: str = "desc",
    after: Optional[datetime] = None
) -> Tuple[List[dict], int]:
    """
    Retrieve notifications with advanced filtering, cursor boundary, sorting, and pagination.
    """
    username = username.lower().strip()
    
    # 1. Construct dynamic query filters
    query = {"username": username}
    
    if unread_only:
        query["is_read"] = False
        
    if after:
        # ISO-8601 cursor matching: retrieve only items newer than this timestamp
        query["created_at"] = {"$gt": after}

    # 2. Determine sort order
    sort_dir = DESCENDING if sort == "desc" else ASCENDING
    sort_query = [("created_at", sort_dir)]

    # 3. Calculate pagination boundaries
    skip = (page - 1) * page_size
    
    # 4. Execute counting and retrieval concurrently
    total_task = db["notifications"].count_documents(query)
    cursor = db["notifications"].find(query).sort(sort_query).skip(skip).limit(page_size)
    items_task = cursor.to_list(length=page_size)
    
    total, items = await TupleTask(total_task, items_task)
    return items, total

# Helper to await tasks concurrently
async def TupleTask(task1, task2):
    import asyncio
    return await asyncio.gather(task1, task2)


async def mark_notifications_as_read(
    db: AsyncIOMotorDatabase,
    username: str,
    notification_ids: List[str]
) -> int:
    """
    Marks a list of specific notification IDs as read for a given user.
    """
    username = username.lower().strip()
    result = await db["notifications"].update_many(
        {"username": username, "_id": {"$in": notification_ids}},
        {"$set": {"is_read": True}}
    )
    logger.info(f"Marked {result.modified_count} notifications as read for @{username}.")
    return result.modified_count


async def mark_all_notifications_as_read(
    db: AsyncIOMotorDatabase,
    username: str
) -> int:
    """
    Marks all notifications for a given user as read.
    """
    username = username.lower().strip()
    result = await db["notifications"].update_many(
        {"username": username, "is_read": False},
        {"$set": {"is_read": True}}
    )
    logger.info(f"Marked all ({result.modified_count}) notifications as read for @{username}.")
    return result.modified_count


async def bulk_delete_notifications(
    db: AsyncIOMotorDatabase,
    username: str,
    notification_ids: List[str]
) -> int:
    """
    Bulk deletes a list of specific notification IDs for a given user.
    """
    username = username.lower().strip()
    result = await db["notifications"].delete_many(
        {"username": username, "_id": {"$in": notification_ids}}
    )
    logger.info(f"Bulk deleted {result.deleted_count} notifications for @{username}.")
    return result.deleted_count


async def get_unread_count(
    db: AsyncIOMotorDatabase,
    username: str
) -> int:
    """
    Return count of unread notifications for a user.
    """
    username = username.lower().strip()
    count = await db["notifications"].count_documents({"username": username, "is_read": False})
    return count


# --- Mention Analytics Operations (Bonus) ---

async def get_mention_analytics(
    db: AsyncIOMotorDatabase,
    username: str
) -> Tuple[int, List[dict]]:
    """
    Provides analytical insights about mentions for a given user using MongoDB aggregation frameworks.
    Returns (total_mentions, top_mentioners).
    """
    username = username.lower().strip()
    
    # 1. Count total mentions
    total_mentions = await db["notifications"].count_documents({"username": username})
    
    # 2. Find top mentioners using $lookup join on comments
    pipeline = [
        # Filter notifications for the target user
        {"$match": {"username": username}},
        # Join with the comments collection to fetch author metadata
        {
            "$lookup": {
                "from": "comments",
                "localField": "comment_id",
                "foreignField": "_id",
                "as": "comment_details"
            }
        },
        # Unwind the array resulting from the join
        {"$unwind": "$comment_details"},
        # Group by comment author and sum up the frequency
        {
            "$group": {
                "_id": "$comment_details.author",
                "count": {"$sum": 1}
            }
        },
        # Sort by mention frequency in descending order
        {"$sort": {"count": -1}},
        # Limit to top 5 mentioners
        {"$limit": 5},
        # Reshape output schema
        {
            "$project": {
                "author": "$_id",
                "count": 1,
                "_id": 0
            }
        }
    ]
    
    cursor = db["notifications"].aggregate(pipeline)
    top_mentioners = await cursor.to_list(length=5)
    
    return total_mentions, top_mentioners

import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, Path, Body, status, WebSocket, WebSocketDisconnect
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.database import get_db
from app.schemas import (
    NotificationListResponse,
    ReadNotificationsRequest,
    BulkDeleteRequest,
    UnreadCountResponse
)
from app.crud import (
    get_notifications,
    mark_notifications_as_read,
    mark_all_notifications_as_read,
    bulk_delete_notifications,
    get_unread_count
)
from app.websocket_manager import ws_manager

logger = logging.getLogger("app.routers.notifications")
router = APIRouter()

@router.get(
    "/notifications/{username}",
    response_model=NotificationListResponse,
    status_code=status.HTTP_200_OK
)
async def fetch_notifications(
    username: str = Path(..., description="The user to retrieve notifications for"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    unread_only: bool = Query(False, description="Filter for unread notifications only"),
    sort: str = Query("desc", regex="^(asc|desc)$", description="Sort order by created_at"),
    after: Optional[datetime] = Query(None, description="ISO-8601 cursor to filter notifications after this timestamp"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Retrieve paginated notifications for a given user, including optional sorting,
    read/unread filtering, and timestamp cursor filtering.
    """
    username = username.lower().strip()
    
    items, total = await get_notifications(
        db=db,
        username=username,
        page=page,
        page_size=page_size,
        unread_only=unread_only,
        sort=sort,
        after=after
    )
    
    # Calculate if there is a next page
    skip = (page - 1) * page_size
    has_next = total > (skip + len(items))
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": has_next,
        "items": items
    }


@router.patch(
    "/notifications/{username}/read",
    status_code=status.HTTP_200_OK
)
async def mark_read(
    username: str = Path(..., description="The user owning the notifications"),
    payload: ReadNotificationsRequest = Body(..., description="IDs to mark as read"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Mark specific notification IDs as read.
    """
    username = username.lower().strip()
    modified_count = await mark_notifications_as_read(db, username, payload.ids)
    return {"message": f"Successfully marked {modified_count} notifications as read."}


@router.patch(
    "/notifications/{username}/read-all",
    status_code=status.HTTP_200_OK
)
async def mark_all_read(
    username: str = Path(..., description="The user owning the notifications"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Mark all notifications as read.
    """
    username = username.lower().strip()
    modified_count = await mark_all_notifications_as_read(db, username)
    return {"message": f"Successfully marked all ({modified_count}) notifications as read."}


@router.delete(
    "/notifications/{username}/bulk-delete",
    status_code=status.HTTP_200_OK
)
async def bulk_delete(
    username: str = Path(..., description="The user owning the notifications"),
    payload: BulkDeleteRequest = Body(..., description="IDs to delete"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Bulk-delete notification IDs.
    """
    username = username.lower().strip()
    deleted_count = await bulk_delete_notifications(db, username, payload.ids)
    return {"message": f"Successfully deleted {deleted_count} notifications."}


@router.get(
    "/notifications/{username}/unread-count",
    response_model=UnreadCountResponse,
    status_code=status.HTTP_200_OK
)
async def fetch_unread_count(
    username: str = Path(..., description="The user owning the notifications"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Return the total unread notifications count.
    """
    username = username.lower().strip()
    unread_count = await get_unread_count(db, username)
    return {"unread_count": unread_count}


# --- WebSockets Real-Time Push Endpoint ---

@router.websocket("/ws/notifications/{username}")
async def websocket_endpoint(
    websocket: WebSocket,
    username: str = Path(..., description="The user to stream real-time notifications to")
):
    """
    WebSocket endpoint for real-time notification pushes.
    Allows multiple concurrent tab connections per user.
    """
    username = username.lower().strip()
    
    # Register the connection with the manager
    await ws_manager.connect(websocket, username)
    
    try:
        while True:
            # We must maintain a receive loop to capture disconnect events.
            # Client messages can be received and ignored or logged.
            data = await websocket.receive_text()
            # Send periodic heartbeats if necessary, though keep-alive is handled at transport layer.
            
    except WebSocketDisconnect:
        # Gracefully handle normal client closed socket
        logger.info(f"WebSocket connection closed normally for user: {username}")
    except Exception as e:
        logger.error(f"WebSocket error for user {username}: {e}", exc_info=True)
    finally:
        # Always clean up the connection on close/failure to prevent memory leaks!
        await ws_manager.disconnect(websocket, username)

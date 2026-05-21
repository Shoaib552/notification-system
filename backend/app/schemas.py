from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import List, Optional

# --- Comment Schemas ---

class CommentCreate(BaseModel):
    """Schema for incoming comment requests."""
    author: str = Field(..., min_length=1, max_length=100, description="The author posting the comment")
    text: str = Field(..., min_length=1, max_length=2000, description="The text content of the comment (max 2000 chars)")

    @field_validator("author")
    @classmethod
    def sanitize_author(cls, v: str) -> str:
        # Strip trailing and leading whitespaces
        v = v.strip()
        if not v:
            raise ValueError("Author name cannot be empty or just whitespace.")
        # Lowercase author to maintain naming consistency
        return v.lower()

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Comment text cannot be empty or just whitespace.")
        return v

class CommentResponse(BaseModel):
    """Schema for returned comment models."""
    id: str = Field(..., alias="_id")
    text: str
    author: str
    created_at: datetime

    class Config:
        populate_by_name = True


# --- Notification Schemas ---

class NotificationResponse(BaseModel):
    """Schema for returned notification models."""
    id: str = Field(..., alias="_id")
    username: str
    message: str
    is_read: bool
    comment_id: str
    created_at: datetime

    class Config:
        populate_by_name = True


class NotificationListResponse(BaseModel):
    """Pagination envelope for notifications retrieval."""
    total: int
    page: int
    page_size: int
    has_next: bool
    items: List[NotificationResponse]


class ReadNotificationsRequest(BaseModel):
    """Schema to mark specific notification IDs as read."""
    ids: List[str] = Field(..., min_length=1, description="List of notification IDs to mark as read")


class BulkDeleteRequest(BaseModel):
    """Schema to bulk delete specific notification IDs."""
    ids: List[str] = Field(..., min_length=1, description="List of notification IDs to delete")


class UnreadCountResponse(BaseModel):
    """Schema for returning unread notifications count."""
    unread_count: int


# --- Analytics Schemas ---

class MentionerCount(BaseModel):
    author: str
    count: int

class MentionAnalyticsResponse(BaseModel):
    """Schema for analytical breakdown of mentions."""
    username: str
    total_mentions: int
    top_mentioners: List[MentionerCount]

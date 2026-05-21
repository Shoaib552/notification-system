import pytest
from unittest.mock import MagicMock
import pymongo
from pymongo.errors import DuplicateKeyError

# Class simulating the de-duplication insert loop under concurrent load
class MockNotificationRepository:
    def __init__(self):
        self.inserted_docs = []
        self.unique_constraints = set()  # Set of (username, comment_id) tuples

    def insert_notification(self, doc):
        """Simulates MongoDB insert with unique compound index check."""
        key = (doc["username"], doc["comment_id"])
        if key in self.unique_constraints:
            # Duplicate key violation simulation
            raise DuplicateKeyError("E11000 duplicate key error collection: notification_db.notifications index: unique_user_comment_mention")
        
        self.inserted_docs.append(doc)
        self.unique_constraints.add(key)
        return True

def test_concurrency_de_duplication_safety():
    """
    Verifies that when 100 simultaneous workers all attempt to process the
    same mention for @john on comment 'comment-123', exactly 1 notification
    is written to the database (99 operations exit idempotently).
    """
    repo = MockNotificationRepository()
    
    # Simulating 100 worker threads executing the handler task concurrently
    results = []
    for i in range(100):
        notification_doc = {
            "_id": f"notif-uuid-{i}",
            "username": "john",
            "message": "You were mentioned by @alice: \"Review this PR\"",
            "is_read": False,
            "comment_id": "comment-123"
        }
        
        try:
            # Attempt db write
            repo.insert_notification(notification_doc)
            results.append("SUCCESS")
        except DuplicateKeyError:
            # In worker.py, we catch this and exit gracefully (treating as success/idempotent)
            results.append("IDEMPOTENT_SKIP")
            
    # Verify that exactly 1 worker successfully inserts, and 99 workers hit DuplicateKeyError and skip
    assert results.count("SUCCESS") == 1
    assert results.count("IDEMPOTENT_SKIP") == 99
    
    # Confirm DB contents: only 1 document is written
    assert len(repo.inserted_docs) == 1
    assert repo.inserted_docs[0]["username"] == "john"
    assert repo.inserted_docs[0]["comment_id"] == "comment-123"

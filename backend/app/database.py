import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import IndexModel, ASCENDING, DESCENDING
from app.config import settings

# Setup logging
logger = logging.getLogger("app.database")

class Database:
    """
    MongoDB client and database lifecycle management.
    Uses Motor for asynchronous operations.
    """
    client: AsyncIOMotorClient = None
    db = None

    def connect(self):
        """Establish the database connection pool."""
        logger.info(f"Connecting to MongoDB at {settings.MONGODB_URI}")
        self.client = AsyncIOMotorClient(settings.MONGODB_URI)
        self.db = self.client[settings.DATABASE_NAME]
        logger.info("MongoDB client connected.")

    def disconnect(self):
        """Close the database connection pool."""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed.")

    async def setup_indexes(self):
        """
        Creates mandatory indexes in MongoDB.
        Ensures uniqueness of (username, comment_id) for de-duplication
        and optimized performance under high query load.
        """
        if self.db is None:
            raise RuntimeError("Database not initialized. Call connect() first.")

        # 1. Setup comments indexes
        comments_col = self.db["comments"]
        # Index on author and created_at for filters & sorting
        comment_indexes = [
            IndexModel([("author", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)])
        ]
        await comments_col.create_indexes(comment_indexes)
        logger.info("Comments collection indexes created/verified.")

        # 2. Setup notifications indexes
        notifications_col = self.db["notifications"]
        
        # Compound Unique index on (username, comment_id) -> CRITICAL for race condition prevention!
        compound_unique_index = IndexModel(
            [("username", ASCENDING), ("comment_id", ASCENDING)],
            unique=True,
            name="unique_user_comment_mention"
        )
        
        # Standard index on username for paginated retrieval
        username_index = IndexModel([("username", ASCENDING)], name="user_notifications_idx")
        created_at_index = IndexModel([("created_at", DESCENDING)], name="notification_date_idx")

        await notifications_col.create_indexes([
            compound_unique_index,
            username_index,
            created_at_index
        ])
        logger.info("Notifications collection indexes created/verified (including compound unique index).")

# Global singleton instance
db_manager = Database()

def get_db():
    """FastAPI Dependency to get the MongoDB database database."""
    if db_manager.db is None:
        raise RuntimeError("Database client is not connected.")
    return db_manager.db

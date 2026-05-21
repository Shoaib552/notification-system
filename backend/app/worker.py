import os
import uuid
import json
import logging
import contextvars
from datetime import datetime, timezone
from celery import Celery
import pymongo
from pymongo.errors import DuplicateKeyError
import redis

# --- Worker Correlation ID Context ---
correlation_id_ctx = contextvars.ContextVar("correlation_id", default="CELERY-BOOT")

class JSONFormatter(logging.Formatter):
    """
    Custom logging formatter for the Celery worker, outputting logs in structured JSON
    with correlation IDs propagated from the API HTTP thread.
    """
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_ctx.get()
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

def setup_worker_logging():
    root_logger = logging.getLogger()
    root_logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)

# Configure Celery logger with the exact same JSON format!
setup_worker_logging()
logger = logging.getLogger("app.worker")

# Define Celery app
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery_app = Celery(
    "notification_worker",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1
)

mongo_client = None
db = None
redis_client = None

def init_clients():
    global mongo_client, db, redis_client
    if mongo_client is None:
        mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        db_name = os.getenv("DATABASE_NAME", "notification_db")
        logger.info(f"Worker connecting to MongoDB: {mongo_uri}")
        mongo_client = pymongo.MongoClient(mongo_uri)
        db = mongo_client[db_name]

    if redis_client is None:
        redis_uri = os.getenv("REDIS_URI", "redis://localhost:6379/0")
        logger.info(f"Worker connecting to Redis: {redis_uri}")
        redis_client = redis.Redis.from_url(redis_uri, decode_responses=True)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=5)
def deliver_mention_notification(
    self,
    username: str,
    comment_id: str,
    author: str,
    comment_text: str,
    correlation_id: str = ""
):
    """
    Background worker task to persist a notification and broadcast it to connected WS clients.
    
    Guarantees:
    - Concurrency Safety: Handled via MongoDB compound unique index. Catching DuplicateKeyError makes it idempotent.
    - Fault Tolerance: Auto-retries on connection/system failures with Celery retries.
    - Decoupled Push: Publishes to Redis Pub/Sub, freeing worker from managing WS connections.
    - Observability: Propagates the correlation ID across network barriers to maintain trace logs.
    """
    # 1. Bind correlation ID for this worker thread context
    corr_id = correlation_id or f"WORKER-{uuid.uuid4()}"
    token = correlation_id_ctx.set(corr_id)
    
    try:
        init_clients()
        
        username = username.lower().strip()
        author = author.lower().strip()
        
        logger.info(f"Processing mention for @{username} on comment {comment_id} from {author}")
        
        # 2. Check if comment exists
        comments_col = db["comments"]
        comment = comments_col.find_one({"_id": comment_id})
        if not comment:
            logger.error(f"Comment {comment_id} not found in database. Aborting notification.")
            return f"Aborted: Comment {comment_id} does not exist."
        
        # 3. Formulate Notification Document
        notification_id = str(uuid.uuid4())
        snippet = comment_text[:60] + "..." if len(comment_text) > 60 else comment_text
        message = f"You were mentioned by @{author}: \"{snippet}\""
        
        now = datetime.now(timezone.utc)
        
        notification_doc = {
            "_id": notification_id,
            "username": username,
            "message": message,
            "is_read": False,
            "comment_id": comment_id,
            "created_at": now
        }
        
        # 4. Attempt insertion (Concurrency safety check)
        notifications_col = db["notifications"]
        try:
            notifications_col.insert_one(notification_doc)
            logger.info(f"Notification {notification_id} successfully persisted for @{username}.")
        except DuplicateKeyError:
            logger.warning(f"Duplicate notification detected for user @{username} on comment {comment_id}. Skipping.")
            return "Idempotent: Duplicate notification skipped."
        except pymongo.errors.PyMongoError as exc:
            logger.error(f"MongoDB error: {exc}. Retrying task...")
            raise self.retry(exc=exc)
            
        # 5. Push to Redis Pub/Sub for WebSockets
        try:
            serialized_doc = {**notification_doc, "created_at": now.isoformat()}
            channel_name = f"ws:notification:{username}"
            logger.info(f"Publishing notification to Redis channel: {channel_name}")
            
            redis_client.publish(
                channel_name,
                json.dumps({
                    "type": "new_notification",
                    "data": serialized_doc
                })
            )
        except Exception as exc:
            logger.error(f"Failed to publish WebSocket message to Redis: {exc}")
            
        return f"Success: Notification {notification_id} delivered to @{username}."
        
    finally:
        # Reset context var
        correlation_id_ctx.reset(token)

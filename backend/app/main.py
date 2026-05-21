import os
import uuid
import contextvars
import logging
import json
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import db_manager
from app.redis_client import redis_manager
from app.routers import comments, notifications, health, analytics

# --- Correlation ID & Context Setup ---
# Thread/Task-local context storage for correlation IDs
correlation_id_ctx = contextvars.ContextVar("correlation_id", default="SYSTEM")

class JSONFormatter(logging.Formatter):
    """
    Custom logging formatter that outputs logs as structured JSON.
    Automatically injects the active correlation ID.
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

def setup_logging():
    """Configures the root logger to use structured JSON logging."""
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL)
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)

# Execute logging configuration
setup_logging()
logger = logging.getLogger("app.main")

# --- App Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown processes of the application lifecycle."""
    logger.info("Initializing backend dependencies...")
    # 1. Connect database & create compound indexes
    db_manager.connect()
    await db_manager.setup_indexes()
    
    # 2. Connect Redis connection pool
    redis_manager.connect()
    
    logger.info("Backend dependencies successfully initialized.")
    yield
    # Shutdown processes
    logger.info("Cleaning up backend dependencies...")
    db_manager.disconnect()
    await redis_manager.disconnect()
    logger.info("Backend dependencies cleaned up.")

# --- FastAPI Initialization ---
app = FastAPI(
    title="Production Mention Notification System API",
    description="Real-time mention notification engine using FastAPI, MongoDB, Celery, and Redis.",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for Vite Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify explicit domain origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Global Correlation ID Middleware ---
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """
    Middleware that reads/creates a correlation ID for tracking requests
    across the entire lifecycle (API -> worker -> WebSocket).
    """
    # 1. Get X-Correlation-ID from request header or generate a new one
    corr_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    
    # 2. Set it in the ContextVar context
    token = correlation_id_ctx.set(corr_id)
    
    start_time = time.time()
    logger.info(f"Started {request.method} {request.url.path}")
    
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        logger.info(f"Finished {request.method} {request.url.path} - Status: {response.status_code} in {duration:.4f}s")
        
        # 3. Add correlation ID to response header
        response.headers["X-Correlation-ID"] = corr_id
        return response
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Failed {request.method} {request.url.path} - Error: {e} in {duration:.4f}s", exc_info=True)
        # Return generic error response conforming to structured JSON shape
        return JSONResponse(
            status_code=500,
            content={
                "error": "InternalServerError",
                "message": "An unexpected error occurred. Please contact system support.",
                "correlation_id": corr_id
            }
        )
    finally:
        # Reset the ContextVar token
        correlation_id_ctx.reset(token)

# --- Custom Validation Error Formatting (HTTP 422) ---
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Fallback handler to prevent raw python tracebacks in responses."""
    corr_id = correlation_id_ctx.get()
    logger.error(f"Unhandled Exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": str(exc) if settings.LOG_LEVEL == "DEBUG" else "An unexpected error occurred.",
            "correlation_id": corr_id
        }
    )

# --- Route Inclusions ---
app.include_router(comments.router, tags=["Comments"])
app.include_router(notifications.router, tags=["Notifications"])
app.include_router(health.router, tags=["Health Check"])
app.include_router(analytics.router, tags=["Analytics"])

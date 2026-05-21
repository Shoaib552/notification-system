import asyncio
import json
import logging
from typing import Dict, List
from fastapi import WebSocket
from app.config import settings
from app.redis_client import get_redis

logger = logging.getLogger("app.websocket_manager")

class ConnectionManager:
    """
    Manages active WebSocket connections per user.
    Leverages Redis Pub/Sub to support real-time pushing from separate background workers.
    """
    def __init__(self):
        # Maps user -> list of active WebSocket connections (handles multi-tab concurrency!)
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # Maps user -> active Redis Pub/Sub listener task
        self.pubsub_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, username: str):
        """Register a new client connection and start the Redis Pub/Sub listener if needed."""
        await websocket.accept()
        username = username.lower()

        if username not in self.active_connections:
            self.active_connections[username] = []
            
        self.active_connections[username].append(websocket)
        logger.info(f"WebSocket client connected: {username} (Total connections: {len(self.active_connections[username])})")

        # If this is the first connection for the user, spin up a Redis Pub/Sub listener task
        if username not in self.pubsub_tasks:
            task = asyncio.create_task(self._listen_redis_channel(username))
            self.pubsub_tasks[username] = task

    async def disconnect(self, websocket: WebSocket, username: str):
        """Remove a client connection and clean up listeners if no connections remain."""
        username = username.lower()
        if username in self.active_connections:
            if websocket in self.active_connections[username]:
                self.active_connections[username].remove(websocket)
                logger.info(f"WebSocket client disconnected: {username}")
                
            if not self.active_connections[username]:
                # No more active tabs/connections for this user. Clean up resources.
                del self.active_connections[username]
                if username in self.pubsub_tasks:
                    self.pubsub_tasks[username].cancel()
                    del self.pubsub_tasks[username]
                    logger.info(f"Cancelled Redis Pub/Sub listener for user: {username}")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Direct push to a single connection."""
        await websocket.send_text(json.dumps(message))

    async def broadcast_to_user(self, username: str, message: dict):
        """Broadcast a message locally to all active connections (tabs) of a user."""
        username = username.lower()
        if username in self.active_connections:
            logger.info(f"Broadcasting notification to {username} over {len(self.active_connections[username])} connections.")
            # Gather tasks to send concurrently to all tabs
            tasks = [connection.send_text(json.dumps(message)) for connection in self.active_connections[username]]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _listen_redis_channel(self, username: str):
        """
        Background asyncio task that listens on the Redis Pub/Sub channel
        for a specific user and broadcasts messages locally to their active connections.
        """
        username = username.lower()
        channel_name = f"{settings.WS_CHANNEL_PREFIX}{username}"
        redis = get_redis()
        
        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(channel_name)
            logger.info(f"Subscribed to Redis Pub/Sub channel: {channel_name}")
            
            while True:
                # Poll for messages (yields control to event loop)
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    payload = message["data"]
                    try:
                        data = json.loads(payload)
                        # Broadcast the received Redis message to all user's active sockets in this process
                        await self.broadcast_to_user(username, data)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON payload on channel {channel_name}: {payload}")
                
                # Yield control to prevent CPU spin
                await asyncio.sleep(0.01)
                
        except asyncio.CancelledError:
            logger.info(f"Stopping Redis Pub/Sub channel listener for: {channel_name}")
        except Exception as e:
            logger.error(f"Error in Redis Pub/Sub channel listener for {channel_name}: {e}", exc_info=True)
        finally:
            # Clean up subscription
            try:
                await pubsub.unsubscribe(channel_name)
                await pubsub.close()
            except Exception:
                pass

# Global manager instance
ws_manager = ConnectionManager()

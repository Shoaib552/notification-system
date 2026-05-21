# Notifier: Production-Grade Real-Time @Mention Notification Broker

Notifier is a production-grade, highly scalable asynchronous mention notification broker. It intercepts `@mentions` within public discussion boards, processes them decoupled in background Celery workers, manages database-level concurrency safety using MongoDB unique indexes, and streams real-time updates over WebSockets using Redis Pub/Sub.

---

##  Architecture & System Design

Below is the complete architectural flow, from a client posting a comment to an asynchronous background worker delivering the notification and executing a distributed real-time push:

```
                  ┌─────────────────────────────────────────┐
                  │              React Client               │
                  └────────────┬────────────────────────────┘
                               │
                               │ 1. POST /comments
                               ▼
                  ┌─────────────────────────────────────────┐
                  │            FastAPI Gateway              │◄────┐
                  │   - Enforces Redis sliding-window RL    │     │ 4. Streams events
                  │   - Persists comment in MongoDB         │     │    over WebSockets
                  │   - Dispatches jobs to Redis broker     │     │
                  └──────┬──────────────────────────┬───────┘     │
                         │                          │             │
        2. Enqueues      │                          │             │
        asynchronous     │                          │             │
        mention tasks    ▼                          │             │
                  ┌──────────────────────┐          │             │
                  │   Redis Broker/Queue │          │             │
                  └──────────┬───────────┘          │             │
                             │                      │             │
                             │ 3. Dequeues task     │             │
                             ▼                      ▼             │
                  ┌──────────────────────┐    ┌─────────────┐     │
                  │    Celery Worker     ├───►│    Redis    ├─────┘
                  │  - Persists notif    │    │   Pub/Sub   │  (Horizontally scales
                  │    idempotently      │    │  "ws:john"  │   WebSocket gateways!)
                  │  - Publishes to PubSub    └─────────────┘
                  └──────────┬───────────┘
                             │
                             │ 3.5 insert_one()
                             ▼
                  ┌──────────────────────┐
                  │    MongoDB Storage   │
                  │  - Unique Index on   │
                  │  (user, comment_id)  │
                  └──────────────────────┘
```

### Key Architectural Decoupling
1. **API to Worker**: The API returns an instant `201 Created` to the client. The CPU-heavy regex parsing and network-bound notification delivery are completely offloaded to Celery.
2. **Horizontal WebSockets Push**: WebSockets connections are in-memory. However, workers execute in separate processes. We use **Redis Pub/Sub** to bridge this gap: workers publish notifications to a user-specific Redis channel, and all connected FastAPI instances listen to Redis and push to the user's active socket tabs. This supports unlimited concurrent instances and tabs!

---

##  Getting Started

### Prerequisites
- Docker & Docker Compose installed.

### Option A: The Docker Orchestra (Recommended)
You can boot the entire ecosystem, including the frontend, API gateways, workers, database, and Redis cache, with a single command:

```bash
docker-compose up --build
```

#### Access Ports:
- **React Frontend Panel**: [http://localhost:3000](http://localhost:3000)
- **FastAPI API Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check Endpoint**: [http://localhost:8000/health](http://localhost:8000/health)

---

### Option B: Local Development (Bare Metal)

If you wish to run the components separately:

#### 1. Setup Environment
Ensure Redis and MongoDB are running locally on standard ports:
- Redis: `127.0.0.1:6379`
- MongoDB: `127.0.0.1:27017`

Copy the environmental example variables:
```bash
cp .env.example .env
```

#### 2. Start the Backend API
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 3. Start the Celery Worker
```bash
cd backend
source venv/bin/activate
celery -A app.worker.celery_app worker --loglevel=info
```

#### 4. Start the React Frontend
```bash
cd frontend
npm install
npm run dev
```

---

##  Concurrency, Idempotency & DB Guarantees

### Scenario: 100 Simultaneous POST Requests Mentions `@john`

#### 1. How do you prevent duplicate notifications when two workers process the same mention simultaneously?
Notifier uses a database-level **Compound Unique Index** on the `notifications` collection:
```json
{ "username": 1, "comment_id": 1 }
```
When Celery workers process duplicate tasks, they perform a standard write (`insert_one`). 
- The first worker's write is atomic and succeeds.
- All subsequent concurrent writes attempting to insert the exact same `(username, comment_id)` combination fail at the database level with a `pymongo.errors.DuplicateKeyError`.
- The background worker catches this exception and returns gracefully, treating the operation as a successful, idempotent skip. No duplicate records are ever created.

#### 2. What DB-level guarantees do you rely on?
- **Index Constraints**: MongoDB compound unique index guarantees that no duplicate keys can exist in the collection under concurrent race conditions.
- **Single-Document Atomicity**: MongoDB guarantees that write operations to a single document are fully atomic. Since we insert or identify unique constraints at the single document write layer, race conditions are mathematically eliminated at the engine level.

#### 3. What happens if a Redis job fails mid-processing? Is it retried? Is it idempotent?
- **Retry Mechanism**: Celery tasks are bound (`bind=True`) and catch network/system connection errors. In the event of MongoDB disconnects or network failures, the task is automatically rescheduled using Celery's exponential backoff retry policies (up to 3 retries, starting with 5s delay).
- **Idempotency Guarantee**: Because the database write is guarded by the unique compound index, retrying a failed task is fully safe. If the task succeeded in writing to MongoDB but failed during the WebSocket push phase, the retry will hit a `DuplicateKeyError`, log a warning, skip the DB write, and return gracefully.

---

##  API Specification

### Comments
- **`POST /comments`**: Creates a new comment. Extracted mentions are pushed to workers.
  - *Payload*: `{ "author": "alice", "text": "Hey @john review this" }`
  - *Response*: `201 Created`
  - *Rate Limit*: Max 30 requests/minute. Returns `429 Too Many Requests` with a `Retry-After: <seconds>` header.

### Notifications
- **`GET /notifications/{username}`**: Fetch notifications with filters & cursor pagination.
  - *Params*:
    - `page` (default: 1)
    - `page_size` (default: 20, max: 100)
    - `unread_only` (default: false)
    - `sort` (default: desc)
    - `after` (ISO-8601 cursor, e.g. `2024-01-01T00:00:00Z`)
  - *Response*: `total`, `page`, `page_size`, `has_next`, `items`
- **`PATCH /notifications/{username}/read`**: Mark specific notification IDs as read.
  - *Payload*: `{ "ids": ["uuid-1", "uuid-2"] }`
- **`PATCH /notifications/{username}/read-all`**: Mark all notifications as read.
- **`DELETE /notifications/{username}/bulk-delete`**: Bulk delete specific notifications.
  - *Payload*: `{ "ids": ["uuid-1", "uuid-2"] }`
- **`GET /notifications/{username}/unread-count`**: Return unread badge count.
- **`WS /ws/notifications/{username}`**: Establish real-time persistent push socket connection. Supports multiple open tabs concurrently.

### Health
- **`GET /health`**: Deep component health validation (pings MongoDB and Redis). Returns `200 OK` or `503 Service Unavailable`.

### Analytics (Bonus)
- **`GET /analytics/mentions?username={username}`**: Aggregates top mentioners using MongoDB pipelines.

---

##  Premium Visual Experience

The frontend is custom-styled with a **Vanilla CSS Glassmorphic Dark Theme** featuring:
- **Micro-Animations**: Real-time pulses for WebSockets connectivity, hover slides, click contractions, and floating toast announcements.
- **Multi-Tab Simulation**: You can select the logged-in user and comment author separately in the UI to immediately simulate real-time notification dispatches between different tabs and users.
- **Responsive Layout**: Designed for seamless utility on desktop monitors and mobile devices.
- **SEO Ready**: Features proper semantics, distinct element IDs, meta descriptions, and Google typography.

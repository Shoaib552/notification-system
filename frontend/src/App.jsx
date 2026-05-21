import React, { useState, useEffect, useRef } from 'react';

// Configuration (points to local Docker/Compose ports)
const API_BASE = 'http://localhost:8000';
const WS_BASE = 'ws://localhost:8000';

export default function App() {
  // Session States
  const [currentUser, setCurrentUser] = useState('john');
  const [authorInput, setAuthorInput] = useState('alice');
  const [wsStatus, setWsStatus] = useState('disconnected');
  
  // Data States
  const [comments, setComments] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [analytics, setAnalytics] = useState({ total_mentions: 0, top_mentioners: [] });
  
  // UI Control States
  const [commentText, setCommentText] = useState('');
  const [isPosting, setIsPosting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [toasts, setToasts] = useState([]);
  
  // Filtering & Pagination States
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [hasNext, setHasNext] = useState(false);
  const [totalNotifications, setTotalNotifications] = useState(0);

  // WebSocket reference
  const wsRef = useRef(null);

  // 1. Fetch Comments Feed
  const fetchComments = async () => {
    try {
      const res = await fetch(`${API_BASE}/comments`);
      if (res.ok) {
        const data = await res.json();
        setComments(data);
      }
    } catch (err) {
      console.error("Error fetching comments:", err);
    }
  };

  // 2. Fetch Notifications List
  const fetchNotifications = async () => {
    try {
      const filterQuery = unreadOnly ? '&unread_only=true' : '';
      const res = await fetch(`${API_BASE}/notifications/${currentUser}?page=${page}&page_size=${pageSize}${filterQuery}`);
      if (res.ok) {
        const data = await res.json();
        setNotifications(data.items);
        setTotalNotifications(data.total);
        setHasNext(data.has_next);
      }
    } catch (err) {
      console.error("Error fetching notifications:", err);
    }
  };

  // 3. Fetch Unread Count
  const fetchUnreadCount = async () => {
    try {
      const res = await fetch(`${API_BASE}/notifications/${currentUser}/unread-count`);
      if (res.ok) {
        const data = await res.json();
        setUnreadCount(data.unread_count);
      }
    } catch (err) {
      console.error("Error fetching unread count:", err);
    }
  };

  // 4. Fetch Analytics Panel (Bonus)
  const fetchAnalytics = async () => {
    try {
      const res = await fetch(`${API_BASE}/analytics/mentions?username=${currentUser}`);
      if (res.ok) {
        const data = await res.json();
        setAnalytics(data);
      }
    } catch (err) {
      console.error("Error fetching analytics:", err);
    }
  };

  // Initial Bootstrap & trigger on User Switch
  useEffect(() => {
    fetchComments();
  }, []);

  useEffect(() => {
    setPage(1); // Reset page on user switch
    setSelectedIds(new Set());
    fetchNotifications();
    fetchUnreadCount();
    fetchAnalytics();
  }, [currentUser, unreadOnly, pageSize]);

  useEffect(() => {
    fetchNotifications();
  }, [page]);

  // 5. Establish Real-Time WebSocket Connection
  useEffect(() => {
    setWsStatus('connecting');
    let reconnectTimeout = null;

    const connectWebSocket = () => {
      if (wsRef.current) {
        wsRef.current.close();
      }

      const wsUrl = `${WS_BASE}/ws/notifications/${currentUser}`;
      console.log(`Connecting to WebSocket: ${wsUrl}`);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("WebSocket connected.");
        setWsStatus('connected');
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'new_notification') {
            const newNotif = message.data;
            
            // 1. Prepend to current notification view if on Page 1
            if (page === 1) {
              setNotifications(prev => [newNotif, ...prev.slice(0, pageSize - 1)]);
            }
            
            // 2. Increment counters
            setUnreadCount(prev => prev + 1);
            setTotalNotifications(prev => prev + 1);
            
            // 3. Trigger floating Toast notification
            triggerToast(newNotif);
            
            // 4. Refresh analytics
            fetchAnalytics();
          }
        } catch (err) {
          console.error("Error processing WebSocket payload:", err);
        }
      };

      ws.onclose = (event) => {
        console.log("WebSocket disconnected.");
        setWsStatus('disconnected');
        
        // Auto-reconnection logic with backoff
        reconnectTimeout = setTimeout(() => {
          console.log("Attempting WebSocket reconnection...");
          connectWebSocket();
        }, 3000);
      };

      ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        ws.close();
      };
    };

    connectWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
      }
    };
  }, [currentUser]);

  // Toast Trigger Helper
  const triggerToast = (notif) => {
    const toastId = Date.now();
    setToasts(prev => [...prev, { id: toastId, message: notif.message }]);
    
    // Auto fade toast in 5s
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== toastId));
    }, 5000);
  };

  // 6. Comments Submission (triggers Mention flow)
  const handlePostComment = async (e) => {
    e.preventDefault();
    if (!commentText.trim()) return;

    setIsPosting(true);
    setErrorMessage('');

    try {
      const res = await fetch(`${API_BASE}/comments`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Correlation-ID': `UI-${Date.now()}`
        },
        body: JSON.stringify({
          author: authorInput,
          text: commentText
        })
      });

      if (res.status === 201) {
        setCommentText('');
        // Immediately fetch comments list to update UI
        await fetchComments();
        
        // If the author mentions the current user, or if we want to update the stats
        setTimeout(() => {
          fetchUnreadCount();
          fetchNotifications();
        }, 800); // Small buffer for async worker to complete
      } else if (res.status === 429) {
        const retryAfter = res.headers.get('Retry-After') || '60';
        setErrorMessage(`Rate limit exceeded! Please wait ${retryAfter} seconds before comment posting again.`);
      } else {
        const errData = await res.json();
        setErrorMessage(errData.detail || "An error occurred while creating comment.");
      }
    } catch (err) {
      setErrorMessage("Network error connecting to backend API.");
      console.error(err);
    } finally {
      setIsPosting(false);
    }
  };

  // 7. Mark specific notifications as Read
  const handleMarkAsRead = async (ids) => {
    try {
      const res = await fetch(`${API_BASE}/notifications/${currentUser}/read`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids })
      });
      if (res.ok) {
        fetchNotifications();
        fetchUnreadCount();
        setSelectedIds(prev => {
          const next = new Set(prev);
          ids.forEach(id => next.delete(id));
          return next;
        });
      }
    } catch (err) {
      console.error(err);
    }
  };

  // 8. Mark All as Read
  const handleMarkAllRead = async () => {
    try {
      const res = await fetch(`${API_BASE}/notifications/${currentUser}/read-all`, {
        method: 'PATCH'
      });
      if (res.ok) {
        fetchNotifications();
        fetchUnreadCount();
        setSelectedIds(new Set());
      }
    } catch (err) {
      console.error(err);
    }
  };

  // 9. Bulk Delete notifications
  const handleBulkDelete = async (ids) => {
    try {
      const res = await fetch(`${API_BASE}/notifications/${currentUser}/bulk-delete`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids })
      });
      if (res.ok) {
        // Recalculate page boundaries if we delete all items on a page
        fetchNotifications();
        fetchUnreadCount();
        fetchAnalytics();
        setSelectedIds(prev => {
          const next = new Set(prev);
          ids.forEach(id => next.delete(id));
          return next;
        });
      }
    } catch (err) {
      console.error(err);
    }
  };

  // Selection Checkbox toggle helpers
  const handleToggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleToggleSelectAll = () => {
    const pageIds = notifications.map(n => n._id);
    const allSelected = pageIds.every(id => selectedIds.has(id));
    
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (allSelected) {
        pageIds.forEach(id => next.delete(id));
      } else {
        pageIds.forEach(id => next.add(id));
      }
      return next;
    });
  };

  // Comment @mention text decorator utility
  const formatCommentText = (text) => {
    const parts = text.split(/(?<=^|(?<=[^a-zA-Z0-9_\.]))(@[a-zA-Z0-9_]+)/);
    return parts.map((part, idx) => {
      if (part.startsWith('@')) {
        return <span key={idx} className="mention-tag">{part}</span>;
      }
      return part;
    });
  };

  // Filter local items by Search
  const filteredNotifications = notifications.filter(notif => 
    notif.message.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="app-container">
      {/* 1. Header Bar */}
      <header className="glass-panel header-bar">
        <div className="brand-section">
          <span className="brand-logo">🔔</span>
          <div>
            <h1 className="brand-title">Notifier</h1>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Scalable Real-time Mention Broker</p>
          </div>
        </div>

        <div className="session-controls">
          {/* User selection simulation */}
          <div className="user-selector-wrapper">
            <span>Select Active User:</span>
            <select 
              value={currentUser} 
              onChange={(e) => {
                setCurrentUser(e.target.value);
                // Cycle author defaults to another user to make mentions natural
                setAuthorInput(e.target.value === 'john' ? 'alice' : 'john');
              }}
              className="user-select"
            >
              <option value="john">john</option>
              <option value="alice">alice</option>
              <option value="bob">bob</option>
              <option value="charlie">charlie</option>
            </select>
          </div>

          {/* WebSocket Status Indicator */}
          <div className="status-badge">
            <span className={`status-dot ${wsStatus}`}></span>
            <span style={{ textTransform: 'capitalize' }}>WS: {wsStatus}</span>
          </div>
        </div>
      </header>

      {/* 2. Main Grid Layout */}
      <main className="main-grid">
        {/* Left Column: Comments Feed */}
        <section className="section-column">
          <div className="section-title-row">
            <h2 className="section-title">💬 Public Discussion Board</h2>
          </div>

          {/* Comment Composer */}
          <div className="glass-panel comment-composer">
            <form onSubmit={handlePostComment} className="composer-form">
              <div className="composer-meta">
                <span>Posting as:</span>
                <input 
                  type="text" 
                  value={authorInput}
                  onChange={(e) => setAuthorInput(e.target.value.toLowerCase().replace(/\s+/g, ''))}
                  placeholder="Author name"
                  required
                />
              </div>

              {errorMessage && (
                <div className="error-banner">
                  <span>⚠️</span>
                  <span>{errorMessage}</span>
                </div>
              )}

              <div className="textarea-wrapper">
                <textarea
                  className="comment-textarea"
                  value={commentText}
                  onChange={(e) => setCommentText(e.target.value)}
                  placeholder="Add a comment... Hint: mention @john, @alice, @bob, @charlie!"
                  maxLength={2000}
                  required
                />
                <span className={`char-counter ${commentText.length >= 1950 ? 'error' : ''}`}>
                  {commentText.length} / 2000
                </span>
              </div>

              <button 
                type="submit" 
                className="btn-primary"
                disabled={isPosting || !commentText.trim()}
              >
                {isPosting ? 'Posting...' : 'Post Comment & Dispatch'}
              </button>
            </form>
          </div>

          {/* Comments Feed List */}
          <div className="comments-feed">
            {comments.length === 0 ? (
              <div className="glass-panel empty-state">
                <span className="empty-icon">💭</span>
                <p>No comments on this wall yet. Be the first to start the thread!</p>
              </div>
            ) : (
              comments.map(c => (
                <div key={c._id} className="glass-panel comment-card">
                  <div className="comment-header">
                    <span className="comment-author">👤 @{c.author}</span>
                    <span className="comment-date">
                      {new Date(c.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <p className="comment-text">{formatCommentText(c.text)}</p>
                </div>
              ))
            )}
          </div>
        </section>

        {/* Right Column: Notification Hub */}
        <section className="section-column">
          <div className="section-title-row">
            <h2 className="section-title">
              📬 Mention Notification Center
              {unreadCount > 0 && <span className="badge-count">{unreadCount} unread</span>}
            </h2>
          </div>

          <div className="glass-panel notification-inbox">
            <div className="inbox-controls">
              <div className="filters-row">
                <div className="tab-buttons">
                  <button 
                    onClick={() => setUnreadOnly(false)} 
                    className={`tab-btn ${!unreadOnly ? 'active' : ''}`}
                  >
                    All Notifications
                  </button>
                  <button 
                    onClick={() => setUnreadOnly(true)} 
                    className={`tab-btn ${unreadOnly ? 'active' : ''}`}
                  >
                    Unread Only
                  </button>
                </div>

                <div className="bulk-actions">
                  <button 
                    onClick={handleMarkAllRead} 
                    className="btn-secondary"
                    disabled={unreadCount === 0}
                  >
                    Mark All Read
                  </button>
                  <button 
                    onClick={() => handleBulkDelete(Array.from(selectedIds))}
                    className="btn-secondary"
                    style={{ color: selectedIds.size > 0 ? 'var(--color-danger)' : 'inherit' }}
                    disabled={selectedIds.size === 0}
                  >
                    Delete Selected ({selectedIds.size})
                  </button>
                </div>
              </div>

              {/* Local Search */}
              <div className="search-input-wrapper">
                <input 
                  type="text" 
                  className="search-input"
                  placeholder="Search notifications..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                />
              </div>
            </div>

            {/* List */}
            <div className="notification-list">
              {filteredNotifications.length === 0 ? (
                <div className="empty-state">
                  <span className="empty-icon">✉️</span>
                  <p>You're all caught up! No notifications for @{currentUser}.</p>
                </div>
              ) : (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0 0.5rem 0.5rem 0.5rem', borderBottom: '1px solid var(--border-light)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    <input 
                      type="checkbox" 
                      className="notification-checkbox" 
                      onChange={handleToggleSelectAll}
                      checked={notifications.length > 0 && notifications.map(n => n._id).every(id => selectedIds.has(id))}
                    />
                    <span>Select All on Page</span>
                  </div>

                  {filteredNotifications.map(n => (
                    <div key={n._id} className={`glass-panel notification-item ${!n.is_read ? 'unread' : ''}`}>
                      <input 
                        type="checkbox" 
                        className="notification-checkbox" 
                        checked={selectedIds.has(n._id)}
                        onChange={() => handleToggleSelect(n._id)}
                      />
                      
                      <div className="notification-content">
                        <p className="notification-message">{n.message}</p>
                        
                        <div className="notification-meta">
                          <span className="notification-time">
                            ⏱️ {new Date(n.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                          </span>
                          
                          <div className="item-actions">
                            {!n.is_read && (
                              <button 
                                onClick={() => handleMarkAsRead([n._id])} 
                                className="icon-btn read-btn" 
                                title="Mark as read"
                              >
                                ✔️
                              </button>
                            )}
                            <button 
                              onClick={() => handleBulkDelete([n._id])} 
                              className="icon-btn delete-btn" 
                              title="Delete notification"
                            >
                              🗑️
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>

            {/* Pagination Controls */}
            {totalNotifications > 0 && (
              <div className="pagination-controls">
                <div>
                  Showing {Math.min(filteredNotifications.length, pageSize)} of {totalNotifications} notifications
                </div>
                
                <div className="pagination-buttons">
                  <button 
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="btn-secondary"
                  >
                    ◀ Prev
                  </button>
                  <span style={{ display: 'flex', alignItems: 'center', padding: '0 0.5rem' }}>
                    Page {page}
                  </span>
                  <button 
                    onClick={() => setPage(p => p + 1)}
                    disabled={!hasNext}
                    className="btn-secondary"
                  >
                    Next ▶
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* 3. Analytics Panel (Bonus) */}
          <div className="section-title-row" style={{ marginTop: '1rem' }}>
            <h2 className="section-title">📊 @Mention Analytics Summary</h2>
          </div>
          <div className="glass-panel analytics-card">
            <div className="analytics-grid">
              <div className="analytics-stat-row">
                <span className="stat-title">Total Mentions Logged</span>
                <span className="stat-value">{analytics.total_mentions}</span>
              </div>

              <div>
                <h4 style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '0.75rem', fontWeight: 600 }}>
                  Top Mentioners Frequency Breakdown (Top 5)
                </h4>
                {analytics.top_mentioners.length === 0 ? (
                  <p style={{ fontStyle: 'italic', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                    No mention analytics available for this user yet.
                  </p>
                ) : (
                  <div className="mentioners-list">
                    {analytics.top_mentioners.map((m, idx) => {
                      const maxCount = analytics.top_mentioners[0]?.count || 1;
                      const percentage = (m.count / maxCount) * 100;
                      return (
                        <div key={idx} className="mentioner-row">
                          <div className="mentioner-meta">
                            <span className="mentioner-name">👤 @{m.author}</span>
                            <span className="mentioner-count">{m.count} times</span>
                          </div>
                          <div className="progress-bar-container">
                            <div className="progress-bar-fill" style={{ width: `${percentage}%` }}></div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* Floating WebSockets Toast Containers */}
      <div className="toast-container">
        {toasts.map(toast => (
          <div key={toast.id} className="toast-item">
            <button 
              className="toast-close" 
              onClick={() => setToasts(prev => prev.filter(t => t.id !== toast.id))}
            >
              ✖
            </button>
            <div className="toast-body">
              <div className="toast-title">
                <span>🔔</span> New Mention Alert!
              </div>
              <p className="toast-message">{toast.message}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

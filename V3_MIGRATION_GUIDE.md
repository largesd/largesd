# Blind Debate Adjudicator v3 Migration Guide

## Overview

Version 3 addresses all system concerns identified in the UI/System review:

1. ✅ **Fixed global state** - Session-based debate management
2. ✅ **Added input validation** - Comprehensive validation middleware
3. ✅ **JWT authentication** - Proper auth middleware with secure tokens
4. ✅ **Dynamic topic pages** - Single template replacing static t1-t4 files
5. ✅ **Persistent pending posts** - localStorage for posts pending snapshot

## New Files

### Backend
```
backend/
├── app_v3.py              # New Flask API with session-based debates
├── database_v3.py         # Extended database with user preferences
└── app.py                 # Original (unchanged for backwards compatibility)
```

### Frontend
```
frontend/
├── static/js/
│   ├── common.js          # NEW: Shared utilities (BDA object)
│   └── auth.js            # EXISTING: Authentication utilities
├── topic.html             # NEW: Dynamic topic page
└── new_debate_v3.html     # NEW: Updated debate page using v3 features
```

### Scripts
```
start_server_v3.py         # NEW: Startup script for v3
```

## Key Changes

### 1. Session-Based Debate Management

**Before (v2):**
```python
# Global variable - only one debate at a time
current_debate = None

@app.route('/api/debate')
def get_debate():
    return current_debate  # Global state
```

**After (v3):**
```python
# Session-based - multiple debates per user
def get_session_debate_id():
    # Check query params, headers, or user preferences
    debate_id = request.args.get('debate_id')
    if g.user:
        return get_user_preference(g.user['user_id'], 'active_debate_id')
    return debate_id
```

**Benefits:**
- Users can participate in multiple debates
- Debates are associated with user accounts
- Can share debate links via `?debate_id=xxx`

### 2. Input Validation

**New validation helpers:**
```python
validate_string(value, name, min_length, max_length, required)
validate_side(value, required)
validate_topic_id(value, required)
sanitize_html(text)
```

**Applied to all endpoints:**
- Resolution/Scope: 10-500 chars / 10-2000 chars
- Posts: Facts (5-5000 chars), Inference (5-2000 chars)
- Topic IDs: Alphanumeric only
- HTML sanitization removes script tags and event handlers

### 3. JWT Authentication

**New decorators:**
```python
@login_required       # Requires valid JWT
@optional_auth        # Sets g.user if token present
```

**Token payload:**
```json
{
  "user_id": "user_xxx",
  "email": "user@example.com",
  "display_name": "User Name",
  "exp": "2026-04-12T15:27:00Z"
}
```

**Auth flow:**
1. Register/Login returns JWT token
2. Client stores in localStorage
3. Client sends as `Authorization: Bearer <token>`
4. Server validates and sets `g.user`

### 4. Dynamic Topic Pages

**Before:**
- `topic_t1.html`, `topic_t2.html`, `topic_t3.html`, `topic_t4.html`
- Duplicate code, hard to maintain

**After:**
- Single `topic.html?id=t1`
- Loads topic data via API
- Same template for all topics

**URL migration:**
```
OLD: topic_t1.html
NEW: topic.html?id=t1
```

### 5. Persistent Pending Posts

**Before:**
```javascript
let pendingPosts = [];  // Lost on page refresh
```

**After:**
```javascript
// Stored in localStorage via BDA utility
BDA.addPendingPost(post);    // Saves to localStorage
BDA.loadPendingPosts();      // Loads on init
BDA.clearPendingPosts();     // Clears storage
```

**Benefits:**
- Posts survive page refresh
- Users can close browser and return later
- Visual indicator of pending count

### 6. Shared JavaScript (BDA)

**New `BDA` object provides:**
```javascript
BDA.api(endpoint, options)        // API requests with auth
BDA.loadDebate()                  // Load current debate
BDA.loadSnapshot()                // Load current snapshot
BDA.updateStateStrip(data)        // Update header
BDA.showStatus(msg, isError)      // Show status message
BDA.pendingPosts                  // Array (persisted)
BDA.escapeHtml(text)              // XSS prevention
BDA.formatNumber(num, decimals)   // Number formatting
BDA.toggleHelp()                  // Help panel
```

## API Changes

### New Endpoints
```
POST   /api/auth/register           # User registration
POST   /api/auth/login              # User login
POST   /api/auth/logout             # User logout
GET    /api/auth/me                 # Current user info
GET    /api/debates                 # List user's debates
POST   /api/debates                 # Create debate
GET    /api/debate/:id              # Get specific debate
POST   /api/debate/:id/activate     # Set as active debate
GET    /api/debate/topics/:id       # Get topic details
```

### Modified Endpoints
All endpoints now:
- Support `?debate_id=xxx` parameter
- Use session-based debate lookup
- Validate all inputs
- Return proper error codes

### Deprecated
```
OLD: GET /api/debate                # Still works (returns active debate)
NEW: GET /api/debates               # List all debates
NEW: GET /api/debate/:id            # Get specific debate
```

## Database Changes

### New Tables
```sql
-- User preferences for active debate tracking
CREATE TABLE user_preferences (
    preference_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    pref_key TEXT NOT NULL,
    pref_value TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, pref_key)
);
```

### New Columns
```sql
-- Added to debates table
ALTER TABLE debates ADD COLUMN is_private INTEGER DEFAULT 0;
```

## Migration Steps

### 1. Update Dependencies
```bash
cd debate_system
pip install PyJWT  # If not already installed
```

### 2. Run v3 Server
```bash
# Option A: Use v3 startup script
python start_server_v3.py --debug

# Option B: Direct
python -c "from backend.app_v3 import app; app.run(debug=True)"
```

### 3. Update Frontend Links
Update any links to static topic pages:
```html
<!-- OLD -->
<a href="topic_t1.html">Topic 1</a>

<!-- NEW -->
<a href="topic.html?id=t1">Topic 1</a>
```

### 4. Database Migration
The v3 database class auto-migrates existing databases:
- Adds `is_private` column to debates
- Creates `user_preferences` table
- Existing data is preserved

## Configuration

### Environment Variables
```bash
# Required
export SECRET_KEY="your-secret-key-here"  # For JWT signing

# Optional
export JWT_EXPIRATION_HOURS="24"
export FACT_CHECK_MODE="OFFLINE"
export LLM_PROVIDER="mock"
export NUM_JUDGES="5"
```

### Security Notes
1. **Change SECRET_KEY** in production
2. Use HTTPS in production (JWT tokens)
3. Consider bcrypt/argon2 for password hashing (currently PBKDF2)

## Backwards Compatibility

### API v2 Compatibility
- v2 endpoints still work (app_v2.py)
- Database schema is backwards compatible
- Can run v2 and v3 side-by-side (different ports)

### Frontend Compatibility
- Old HTML pages still work
- New features require `common.js`
- Auth.js unchanged

## Testing

### Quick Test
```bash
# 1. Start v3 server
python start_server_v3.py --debug

# 2. Test health endpoint
curl http://localhost:5000/api/health

# 3. Register a user
curl -X POST http://localhost:5000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"password123","display_name":"Test"}'

# 4. Create debate
curl -X POST http://localhost:5000/api/debates \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"resolution":"Resolved: Test","scope":"Test scope"}'
```

### UI Test
1. Open http://localhost:5000/new_debate_v3.html
2. Register/Login
3. Create a debate
4. Submit posts
5. Refresh page - posts should persist
6. Generate snapshot

## Troubleshooting

### "No active debate" error
- Ensure you're logged in
- Create a debate or select from "My Debates"
- Check browser console for errors

### "Authentication required" error
- Token may have expired
- Log in again
- Check localStorage has `access_token`

### Pending posts not persisting
- Check browser supports localStorage
- Check no private browsing mode
- Check console for localStorage errors

## Performance Considerations

1. **localStorage limit**: ~5-10MB per domain
   - Pending posts are small text, unlikely to hit limit
   - Consider pagination if needed

2. **JWT expiration**: 24 hours default
   - Users need to re-login daily
   - Can be extended via env var

3. **Database queries**: v3 adds user preference lookups
   - Minimal performance impact
   - Can add caching if needed

## Future Enhancements

1. **WebSocket updates** for real-time snapshot updates
2. **Service worker** for offline reading
3. **Pagination** for large debate histories
4. **Redis** for session storage (multi-server deployments)
5. **bcrypt** for password hashing

## Summary

v3 addresses all identified system concerns:

| Concern | v2 | v3 |
|---------|-----|-----|
| Global state | ❌ Single debate | ✅ Session-based |
| Input validation | ❌ Minimal | ✅ Comprehensive |
| Auth middleware | ❌ None | ✅ JWT decorators |
| Topic pages | ❌ Static duplicates | ✅ Dynamic template |
| Pending posts | ❌ Memory only | ✅ localStorage |
| Shared JS | ❌ Inline duplication | ✅ common.js |

Migration is straightforward and backwards compatible.

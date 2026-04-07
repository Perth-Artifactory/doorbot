# Doorbot Migration Plan: TidyAuth → Member Portal API

**Status:** Planning Phase - **OPTION A SELECTED**  
**Priority:** Critical Infrastructure  
**Approach:** Conservative, Test-Heavy, Rollback-Ready  
**Selected Strategy:** Use member_portal-edge_auth daemon with Unix socket communication

---

## Executive Summary

This document outlines the migration plan for upgrading the doorbot access control system from the legacy TidyAuth API to the new Member Portal API. Given the critical nature of doorbot (physical access control), this plan prioritizes safety, thorough testing, and the ability to quickly roll back.

### ✅ Decision: Option A - Edge Auth Daemon

**After analysis, we have selected Option A:** Use the `member_portal-edge_auth` daemon with Unix socket communication. This approach:

- Removes all API client code from doorbot (TidyAuthClient, UserManager)
- Uses edge_auth daemon for all caching, retry logic, and API communication
- Simplifies doorbot to just socket communication and GPIO/Slack handling
- Leverages battle-tested offline handling and sound caching
- Maintains clean separation of concerns

**Files to be deleted:** `tidyauth_client.py`, `user_manager.py`  
**Files to be created:** `socket_client.py` (~100 lines, simple socket communication)  
**Net result:** ~200-300 lines of code removed from doorbot

**Key Constraints:**
- No commits to `member_portal-edge_auth` (read-only reference)
- All changes must be in doorbot feature branch only
- Must maintain 24/7 door access capability
- Production testing will be done in-person with rollback capability

---

## 1. Current State Analysis

### 1.1 TidyAuth Integration (Current)

**File:** `doorbot/doorbot/interfaces/tidyauth_client.py`

The current system uses `TidyAuthClient` with the following characteristics:

| Aspect | Current Implementation |
|--------|------------------------|
| **HTTP Client** | `aiohttp` (async) |
| **Authentication** | Query parameter `?token=<token>` |
| **Base URL** | `http://enclave:5000` (from config.json) |
| **Endpoints** | `GET /`, `GET /api/v1/keys/door`, `GET /api/v1/data/sound` |

**Data Flow:**
```python
# From app.py lines 159-165
tidyauth_client = TidyAuthClient(
    base_url=config.tidyauth_url, token=config.tidyauth_token)
user_manager = UserManager(api_client=tidyauth_client,
                           cache_path=config.tidyauth_cache_file)
```

**Key API Methods:**
- `test_route()` - Validates token with GET `/`
- `get_door_keys()` - Fetches access list with GET `/api/v1/keys/door?token=<>&update=tidyhq`
- `get_sound_data(tidyhq_id)` - Fetches sound URL with GET `/api/v1/data/sound?token=<>&tidyhq_id=<>`

**Data Structure (Current):**
```json
{
  "rfid_key_hex": {
    "name": "User Name",
    "door": true,
    "groups": ["members"],
    "sound": "sound_hash",
    "tidyhq": "tidyhq_user_id",
    "sound_url": "https://..."
  }
}
```

**Caching Strategy:**
- `UserManager` caches to JSON file (`data/user_cache.json`)
- Sound URLs cached alongside user data
- No offline write capability
- Updates triggered periodically via `update_keys()` background task

### 1.2 User Manager (Current)

**File:** `doorbot/doorbot/interfaces/user_manager.py`

The `UserManager` class:
- Wraps `TidyAuthClient`
- Loads keys from disk cache on startup
- `is_key_authorised(key)` - checks if key exists in cache
- `get_user_details(key)` - returns user data
- `download_keys()` - async refresh from API, handles sound URL fetching

### 1.3 Test Coverage (Current)

**Test Framework:** pytest with pytest-asyncio

**Current Test Status:**

| Component | Test Status | Notes |
|-----------|-------------|-------|
| `tidyauth_client.py` | **NO PYTEST TESTS** | Only legacy manual test script (`tidyauth_client_test.py`) |
| `user_manager.py` | **NO PYTEST TESTS** | Only legacy manual test script (`user_manager_test.py`) |
| `app.py` (door functions) | **NO TESTS** | Core door logic untested |
| `app.py` (Slack UI) | **TESTED** | `test_slack_app.py` covers button loading states |
| Hardware interfaces | **MOCKED** | `conftest.py` mocks pigpio, GPIO, etc. |

**Critical Gap:** The API client code and user authorization flow have **zero automated pytest coverage**. This is a major risk for migration.

### 1.4 Configuration (Current)

**File:** `config.json`

```json
{
  "tidyauth": {
    "url": "http://enclave:5000",
    "token": "",
    "cache_file": "data/user_cache.json",
    "update_interval_seconds": 60.0
  }
}
```

---

## 2. New API Analysis (Member Portal)

### 2.1 Member Portal Edge Auth Architecture

The `member_portal-edge_auth` repository provides a helper daemon that interfaces with the new Member Portal API. It can be used in two ways:

1. **As a Daemon** (socket-based integration)
2. **As a Library** (import `PortalClient` directly)

**Architecture Diagram:**
```
┌─────────────────────────────────────────────────────────────────┐
│                         Doorbot (Raspberry Pi)                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Current (TidyAuth)                     │  │
│  │  doorbot → TidyAuthClient → HTTP → TidyAuth Server       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              ↓                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Option A: Daemon                       │  │
│  │  doorbot → Unix Socket → edge_auth daemon → Portal API   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              ↓                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Option B: Direct                       │  │
│  │  doorbot → PortalClient → HTTP → Member Portal API       │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 PortalClient (New API Client)

**File:** `member_portal-edge_auth/edge_auth/portal_client.py`

| Aspect | New Implementation |
|--------|-------------------|
| **HTTP Client** | `requests` (sync) |
| **Authentication** | HTTP Header `X-API-Key: <api_key>` |
| **Base URL** | Configurable (e.g., `http://localhost:5000`) |
| **Endpoints** | `/api/cards/access_list/{name}/revision`, `/api/cards/access_list/{name}`, `/api/door-sounds/{id}`, `/api/timeline/events`, `/api/edge/access-denial` |

**Key API Methods:**

```python
# Authentication: X-API-Key header
client = PortalClient(base_url="http://...", api_key="key")

# GET /api/cards/access_list/{name}/revision
revision = client.get_revision("main-door")

# GET /api/cards/access_list/{name}  
access_list = client.fetch_access_list("main-door")

# GET /api/door-sounds/{id} (streaming download)
sound_path = client.ensure_sound_cached("sound-uuid", cache_dir)

# POST /api/timeline/events
client.post_timeline_grant(
    user_id="uuid", card_id="uuid", card_number="hex",
    access_list_short_name="main-door", device_id="doorbot",
    event_type="edge_access_granted"
)

# POST /api/edge/access-denial
client.post_access_denial(card_number, access_list_short_name, device_id)
```

**Data Structure (New):**
```json
{
  "card_number_hex": {
    "user_id": "uuid",
    "card_id": "uuid", 
    "sound_id": "uuid-or-null"
  }
}
```

### 2.3 Key Differences

| Aspect | TidyAuth (Old) | Member Portal (New) |
|--------|---------------|-------------------|
| **Auth Method** | Query param `?token=` | Header `X-API-Key` |
| **HTTP Library** | aiohttp (async) | requests (sync) |
| **User ID Field** | `tidyhq` (string) | `user_id` (UUID) |
| **Card ID** | Key itself | `card_id` (UUID) |
| **Sound Handling** | URL returned with user data | `sound_id` requires separate download |
| **Offline Writes** | Not supported | Outbox queue for failed writes |
| **Access Denial Logging** | Not supported | Supported via `/api/edge/access-denial` |
| **Sound Caching** | Manual URL management | Built-in cache management |
| **Revision Polling** | Not supported | Built-in revision check |

### 2.4 Edge Auth Daemon Features

If using the daemon approach, additional features are available:

- **Automatic caching** with disk persistence
- **Revision polling** (checks for updates every 30s)
- **Outbox pattern** for offline resilience
- **Sound cache management** (download, prune)
- **Unix socket protocol** for local communication
- **Timeline event posting** (access grants/denials)

---

## 3. Migration Strategies

### 3.1 Option A: Use Edge Auth Daemon (Recommended)

**Approach:** Run `member_portal-edge_auth` as a systemd service, communicate via Unix socket.

**Pros:**
- ✅ Leverages battle-tested caching and offline logic
- ✅ Automatic sound cache management
- ✅ Built-in revision polling
- ✅ Outbox for failed writes
- ✅ Minimal changes to doorbot core logic
- ✅ Can upgrade edge_auth independently

**Cons:**
- ❌ Additional service to deploy and monitor
- ❌ Unix socket communication adds complexity
- ❌ Must handle socket errors/reconnections
- ❌ Requires Python 3.12+ for edge_auth

**Implementation:**
1. Install `member_portal-edge_auth` as a systemd service
2. Create new `SocketAuthClient` class in doorbot
3. Replace `TidyAuthClient` + `UserManager` calls with socket client
4. Handle socket protocol (JSON lines)

**Files to Modify:**
- `doorbot/interfaces/socket_auth_client.py` (NEW)
- `doorbot/app.py` (replace client initialization)
- `config.json` (add socket path config)

### 3.2 Option B: Direct PortalClient Integration

**Approach:** Import `PortalClient` from edge_auth package directly into doorbot.

**Pros:**
- ✅ No additional daemon process
- ✅ Direct HTTP control
- ✅ Simpler deployment (single process)
- ✅ Can wrap with async adapter if needed

**Cons:**
- ❌ Must reimplement caching logic
- ❌ Must reimplement sound caching
- ❌ Must reimplement offline write handling
- ❌ More code changes in doorbot
- ❌ Mixing sync (requests) with async (slack bolt) code

**Implementation:**
1. Add `member_portal-edge_auth` as a dependency or vendor `portal_client.py`
2. Create async wrapper for `PortalClient` (or use sync in async carefully)
3. Adapt `UserManager` to use new data structures
4. Implement caching/offline logic (or adopt simpler approach)

**Files to Modify:**
- `doorbot/interfaces/portal_client.py` (NEW - copy or vendor)
- `doorbot/interfaces/user_manager.py` (MODIFY - adapt to new API)
- `doorbot/app.py` (replace client initialization)
- `config.json` (update auth config)

### 3.3 Recommendation ✅ SELECTED

**SELECTED: Option A (Edge Auth Daemon)**

This option has been selected for implementation. All work will proceed using this approach.

**Rationale:**
1. **Safety:** The edge_auth daemon has built-in caching, offline handling, and sound management. Reimplementing these in doorbot introduces risk.
2. **Maintainability:** The edge_auth project is the "official" client for the Member Portal API. Using it ensures compatibility.
3. **Separation of Concerns:** Doorbot focuses on Slack integration and GPIO control; edge_auth handles API communication.
4. **Simplicity:** Doorbot becomes significantly simpler by removing all API client logic, caching, and sound management.
5. **Testability:** Can test edge_auth independently before integrating.

**What This Means:**
- ❌ **TidyAuthClient** will be completely removed (not adapted)
- ❌ **UserManager** will be completely removed (not adapted)  
- ✅ **New SocketClient** will handle all auth via Unix socket to edge_auth daemon
- ✅ **edge_auth daemon** handles all caching, retries, sound downloads, API calls
- ✅ Doorbot becomes ~200-300 lines simpler

---

## 4. Detailed Implementation Plan

### Phase 1: Preparation and Testing Infrastructure (1-2 weeks)

#### 4.1.1 Create Feature Branch
```bash
git checkout -b feature/member-portal-migration
git push -u origin feature/member-portal-migration
```

#### 4.1.2 Add Test Coverage for Current API

**CRITICAL:** Add pytest tests for current TidyAuth integration BEFORE migration.

**Files to Create:**

```python
# doorbot/tests/test_tidyauth_client.py
"""Tests for TidyAuthClient - baseline before migration."""

import pytest
from unittest.mock import AsyncMock, patch
from doorbot.interfaces.tidyauth_client import TidyAuthClient

@pytest.mark.unit
async def test_get_door_keys_success():
    """Test successful key fetch."""
    client = TidyAuthClient("http://test", "token123")
    
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "abc123": {"name": "Test User", "door": True, "tidyhq": "123"}
    })
    
    with patch("aiohttp.ClientSession.get", return_value=mock_response):
        result = await client.get_door_keys()
    
    assert result is not None
    assert "abc123" in result
    assert result["abc123"]["name"] == "Test User"

@pytest.mark.unit
async def test_get_door_keys_unauthorized():
    """Test handling of 401 response."""
    client = TidyAuthClient("http://test", "bad_token")
    
    mock_response = AsyncMock()
    mock_response.status = 401
    mock_response.raise_for_status.side_effect = Exception("Unauthorized")
    
    with patch("aiohttp.ClientSession.get", return_value=mock_response):
        result = await client.get_door_keys()
    
    assert result is None
```

```python
# doorbot/tests/test_user_manager.py
"""Tests for UserManager - baseline before migration."""

import pytest
import json
import os
from unittest.mock import AsyncMock
from doorbot.interfaces.user_manager import UserManager

@pytest.fixture
def temp_cache(tmp_path):
    return str(tmp_path / "test_cache.json")

@pytest.mark.unit
async def test_is_key_authorised():
    """Test key authorization check."""
    mock_client = AsyncMock()
    cache = {"abc123": {"name": "Test User"}}
    
    with open(temp_cache, "w") as f:
        json.dump(cache, f)
    
    manager = UserManager(mock_client, temp_cache)
    
    assert manager.is_key_authorised("abc123") is True
    assert manager.is_key_authorised("invalid") is False

@pytest.mark.unit
async def test_download_keys_updates_cache():
    """Test that download_keys updates cache file."""
    mock_client = AsyncMock()
    mock_client.get_door_keys = AsyncMock(return_value={
        "newkey": {"name": "New User", "tidyhq": "456"}
    })
    
    manager = UserManager(mock_client, temp_cache)
    changed = await manager.download_keys()
    
    assert changed is True
    assert manager.is_key_authorised("newkey") is True
```

#### 4.1.3 Set Up Edge Auth Daemon (Development)

```bash
# Clone and set up edge auth in development
cd /opt
git clone https://git.artifactory.org.au/Perth-Artifactory/member_portal-edge_auth.git
cd member_portal-edge_auth

# Create .env file
cat > .env << 'EOF'
EDGE_AUTH_API_KEY=your_test_api_key_here
EDGE_AUTH_ACCESS_LIST=main-door
EDGE_AUTH_BASE_URL=http://localhost:5000
EDGE_AUTH_SOCKET_PATH=/tmp/member-portal-edge-auth-dev.sock
EDGE_AUTH_CACHE_FILE=/tmp/access_list_cache_dev.json
EDGE_AUTH_OUTBOX_FILE=/tmp/pending_scans_dev.jsonl
EOF

# Install and run
uv sync
uv run member-portal-edge-auth
```

#### 4.1.4 Update Mock Infrastructure

**File:** `doorbot/tests/conftest.py`

Add mocks for socket communication:

```python
# Add to conftest.py

class MockSocketAuthClient:
    """Mock socket client for testing."""
    
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self._authorized_keys = {"abc123": {"sound_path": "/test/sound.mp3"}}
    
    async def authorize(self, card_number):
        """Mock authorize call."""
        if card_number in self._authorized_keys:
            return {"allowed": True, **self._authorized_keys[card_number]}
        return {"allowed": False, "portal": {"logged": "unknown_scan"}}
    
    async def refresh(self):
        """Mock refresh call."""
        return {"ok": True}

@pytest.fixture
def mock_socket_client():
    return MockSocketAuthClient("/tmp/test.sock")
```

### Phase 2: Implement Socket Client (2-3 weeks)

#### 4.2.1 Create Socket Auth Client

**File:** `doorbot/interfaces/socket_auth_client.py`

```python
"""
Socket-based client for member_portal-edge_auth daemon.
Replaces TidyAuthClient + UserManager with Unix socket communication.
"""

import json
import logging
import asyncio
from pathlib import Path
import aiofiles

logger = logging.getLogger(__name__)

class SocketAuthClient:
    """
    Client for communicating with member_portal-edge_auth daemon via Unix socket.
    
    Protocol: JSON lines (one JSON object per line, newline-terminated)
    
    Authorize request:
        {"card": "30:01:02:bb"}
    
    Response (allowed):
        {"allowed": true, "sound_path": "/path/to/sound.mp3"}
    
    Response (denied):
        {"allowed": false, "portal": {"logged": "unknown_scan"}}
    """
    
    def __init__(self, socket_path: str):
        self.socket_path = Path(socket_path)
        self._lock = asyncio.Lock()
    
    async def authorize(self, card_number: str) -> dict:
        """
        Request authorization for a card number.
        
        Args:
            card_number: The card number (hex string or decimal)
            
        Returns:
            dict with 'allowed' key and optional 'sound_path' or 'portal' info
        """
        async with self._lock:
            try:
                reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
                
                # Send request
                request = json.dumps({"card": card_number}) + "\n"
                writer.write(request.encode())
                await writer.drain()
                
                # Read response
                response_line = await reader.readline()
                writer.close()
                await writer.wait_closed()
                
                if not response_line:
                    logger.error("Empty response from edge_auth")
                    return {"allowed": False, "error": "empty_response"}
                
                return json.loads(response_line.decode().strip())
                
            except FileNotFoundError:
                logger.error(f"Edge auth socket not found: {self.socket_path}")
                return {"allowed": False, "error": "socket_not_found"}
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from edge_auth: {e}")
                return {"allowed": False, "error": "invalid_json"}
            except Exception as e:
                logger.error(f"Socket communication error: {e}")
                return {"allowed": False, "error": str(e)}
    
    async def refresh(self) -> dict:
        """
        Request a forced refresh of the access list cache.
        
        Returns:
            dict with 'ok' key
        """
        async with self._lock:
            try:
                reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
                
                request = json.dumps({"cmd": "refresh"}) + "\n"
                writer.write(request.encode())
                await writer.drain()
                
                response_line = await reader.readline()
                writer.close()
                await writer.wait_closed()
                
                return json.loads(response_line.decode().strip())
                
            except Exception as e:
                logger.error(f"Refresh error: {e}")
                return {"ok": False, "error": str(e)}
    
    async def is_ready(self) -> bool:
        """Check if the edge_auth daemon is available."""
        return self.socket_path.exists()
```

#### 4.2.2 Create Adapter Layer

**File:** `doorbot/interfaces/auth_adapter.py`

```python
"""
Adapter to provide UserManager-like interface over SocketAuthClient.
Eases migration by maintaining similar API.
"""

import logging
from typing import Optional
from doorbot.interfaces.socket_auth_client import SocketAuthClient

logger = logging.getLogger(__name__)

class AuthAdapter:
    """
    Adapter providing UserManager-compatible interface.
    
    This allows gradual migration - existing code expecting UserManager
    methods can use this adapter while underlying implementation uses
    the new socket-based client.
    """
    
    def __init__(self, socket_client: SocketAuthClient):
        self.socket_client = socket_client
    
    def is_key_authorised(self, key: str) -> bool:
        """
        Check if key is authorised (synchronous wrapper).
        
        Note: This is a compatibility shim. New code should use
        async authorize() for proper error handling.
        """
        # For compatibility with existing code
        # In practice, this should be async in new implementation
        import asyncio
        try:
            result = asyncio.get_event_loop().run_until_complete(
                self.socket_client.authorize(key)
            )
            return result.get("allowed", False)
        except Exception as e:
            logger.error(f"Authorization check failed: {e}")
            return False
    
    async def authorize(self, key: str) -> dict:
        """
        Async authorization with full response.
        
        Returns dict with:
        - allowed: bool
        - sound_path: str (optional, if custom sound)
        - portal: dict (optional, portal response info)
        """
        return await self.socket_client.authorize(key)
    
    def key_count(self) -> int:
        """
        Return number of cached keys.
        
        Note: With socket client, this would require a new endpoint.
        For now, return 0 (unknown) or implement via edge_auth extension.
        """
        # TODO: Add endpoint to edge_auth for cache stats
        return 0
    
    def get_user_details(self, key: str) -> Optional[dict]:
        """
        Get user details for a key.
        
        Note: Socket protocol doesn't currently return full user details,
        only authorization result. Consider extending edge_auth protocol.
        """
        # TODO: Extend socket protocol to return user details
        return None
    
    async def download_keys(self) -> bool:
        """
        Trigger a key refresh.
        
        Returns True if refresh was triggered successfully.
        """
        result = await self.socket_client.refresh()
        return result.get("ok", False)
```

#### 4.2.3 Add Tests for Socket Client

**File:** `doorbot/tests/test_socket_auth_client.py`

```python
"""Tests for SocketAuthClient."""

import pytest
import json
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from doorbot.interfaces.socket_auth_client import SocketAuthClient

@pytest.fixture
def socket_client(tmp_path):
    socket_path = tmp_path / "test.sock"
    return SocketAuthClient(str(socket_path))

@pytest.mark.unit
async def test_authorize_success(socket_client, tmp_path):
    """Test successful authorization."""
    socket_client.socket_path = tmp_path / "test.sock"
    
    # Create mock reader/writer
    mock_reader = AsyncMock()
    mock_reader.readline = AsyncMock(return_value=json.dumps({
        "allowed": True,
        "sound_path": "/test/sound.mp3"
    }).encode() + b"\n")
    
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()
    
    with patch("asyncio.open_unix_connection", return_value=(mock_reader, mock_writer)):
        result = await socket_client.authorize("abc123")
    
    assert result["allowed"] is True
    assert result["sound_path"] == "/test/sound.mp3"

@pytest.mark.unit
async def test_authorize_denied(socket_client, tmp_path):
    """Test denied authorization."""
    socket_client.socket_path = tmp_path / "test.sock"
    
    mock_reader = AsyncMock()
    mock_reader.readline = AsyncMock(return_value=json.dumps({
        "allowed": False,
        "portal": {"logged": "unknown_scan"}
    }).encode() + b"\n")
    
    mock_writer = AsyncMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()
    
    with patch("asyncio.open_unix_connection", return_value=(mock_reader, mock_writer)):
        result = await socket_client.authorize("invalid_key")
    
    assert result["allowed"] is False

@pytest.mark.unit
async def test_socket_not_found(socket_client):
    """Test handling when socket doesn't exist."""
    result = await socket_client.authorize("abc123")
    
    assert result["allowed"] is False
    assert result["error"] == "socket_not_found"

@pytest.mark.unit
async def test_refresh(socket_client, tmp_path):
    """Test cache refresh."""
    socket_client.socket_path = tmp_path / "test.sock"
    
    mock_reader = AsyncMock()
    mock_reader.readline = AsyncMock(return_value=json.dumps({
        "ok": True,
        "cmd": "refresh"
    }).encode() + b"\n")
    
    mock_writer = AsyncMock()
    
    with patch("asyncio.open_unix_connection", return_value=(mock_reader, mock_writer)):
        result = await socket_client.refresh()
    
    assert result["ok"] is True
```

### Phase 3: Integrate with App (1-2 weeks)

#### 4.3.1 Modify app.py Initialization

**File:** `doorbot/app.py`

```python
# Around line 159-165, change from:

# OLD CODE:
# tidyauth_client = TidyAuthClient(
#     base_url=config.tidyauth_url, token=config.tidyauth_token)
# user_manager = UserManager(api_client=tidyauth_client,
#                            cache_path=config.tidyauth_cache_file)

# NEW CODE:
from doorbot.interfaces.socket_auth_client import SocketAuthClient
from doorbot.interfaces.auth_adapter import AuthAdapter

socket_client = SocketAuthClient(socket_path=config.edge_auth_socket_path)
user_manager = AuthAdapter(socket_client=socket_client)
```

#### 4.3.2 Update Configuration Schema

**File:** `config.json.template`

```json
{
  "mock_raspberry_pi": false,
  "SLACK_APP_TOKEN": "xapp-test-token",
  "SLACK_BOT_TOKEN": "xoxb-test-token",
  "slack_channel": "#doorbot-slack-test",
  "slack_channel_logs": "#doorbot-test-2",
  "admin_usergroup_handle": "doorbot-admins",
  "relay_channel": "R1",
  "door_sensor_channel": "SW1",
  
  "_comment_tidyauth": "OLD: TidyAuth config - remove after migration",
  "tidyauth": {
    "url": "http://enclave:5000",
    "token": "",
    "cache_file": "data/user_cache.json",
    "update_interval_seconds": 60.0
  },
  
  "_comment_edge_auth": "NEW: Edge Auth config",
  "edge_auth": {
    "socket_path": "run/member-portal-edge-auth.sock",
    "enabled": false
  },
  
  "sounds_dir": "sounds",
  "custom_sounds_dir": "data/custom_sounds",
  "log_path": "data/doorbot.log",
  "access_granted_webhook": "http://ha:8123/api/webhook/xxx",
  "door_sensor_ha_api_url": "http://ha:8123/api/states/binary_sensor.front_door",
  "home_assistant_token": ""
}
```

#### 4.3.3 Update read_tags Function

The `read_tags()` function in `app.py` handles RFID reads. Update to use new auth flow:

```python
# In read_tags() function around line where user_manager.is_key_authorised is called

# OLD:
# if user_manager.is_key_authorised(key):
#     user_details = user_manager.get_user_details(key)
#     sound_file = ...

# NEW:
auth_result = await user_manager.authorize(key)
if auth_result.get("allowed"):
    sound_file = auth_result.get("sound_path")
    # Note: user details not returned by socket protocol currently
    # May need to extend protocol or fetch separately
```

### Phase 4: Testing and Validation (2-3 weeks)

#### 4.4.1 Unit Tests

Run all new tests:
```bash
python -m pytest doorbot/tests/test_socket_auth_client.py -v
python -m pytest doorbot/tests/test_auth_adapter.py -v
```

#### 4.4.2 Integration Tests

Test with actual edge_auth daemon:
```bash
# Terminal 1: Start edge_auth daemon
uv run member-portal-edge-auth

# Terminal 2: Run integration tests
export EDGE_AUTH_SOCKET_PATH=/tmp/member-portal-edge-auth.sock
python -m pytest doorbot/tests/test_integration_member_portal.py -v
```

#### 4.4.3 Manual Testing Checklist

- [ ] Socket connection establishes successfully
- [ ] Authorized card grants access
- [ ] Unauthorized card denies access
- [ ] Custom sounds play correctly
- [ ] Offline mode works (socket unavailable)
- [ ] Slack notifications still work
- [ ] Key refresh command works
- [ ] Graceful degradation when edge_auth down

### Phase 5: Production Deployment (1 week)

#### 4.5.1 Pre-Deployment

1. **Backup current config:**
   ```bash
   cp config.json config.json.backup.$(date +%Y%m%d)
   ```

2. **Install edge_auth as service:**
   ```bash
   sudo cp member_portal-edge_auth/systemd/member-portal-edge-auth.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable member-portal-edge-auth
   ```

3. **Create production .env:**
   ```bash
   sudo mkdir -p /opt/member-portal-edge-auth
   sudo cp .env /opt/member-portal-edge-auth/
   # Edit with production credentials
   ```

#### 4.5.2 Deployment Steps

1. **Start edge_auth daemon:**
   ```bash
   sudo systemctl start member-portal-edge-auth
   sudo systemctl status member-portal-edge-auth
   ```

2. **Update doorbot config:**
   ```bash
   # Add edge_auth config section
   # Set edge_auth.enabled = true
   ```

3. **Restart doorbot:**
   ```bash
   sudo systemctl restart doorbot
   sudo systemctl status doorbot
   ```

4. **Verify:**
   - Check logs: `journalctl -u doorbot -f`
   - Test with known good card
   - Test with known bad card
   - Verify Slack notifications

#### 4.5.3 Rollback Procedure

If issues occur:

1. **Immediate rollback:**
   ```bash
   # Restore old config
   cp config.json.backup.20240115 config.json
   
   # Stop edge_auth
   sudo systemctl stop member-portal-edge-auth
   
   # Restart doorbot (will use old TidyAuth)
   sudo systemctl restart doorbot
   ```

2. **Verify rollback:**
   - Test door access with known card
   - Check logs for errors
   - Monitor for 5 minutes

---

## 5. Data Mapping Reference

### 5.1 User Data Structure Changes

| Old Field (TidyAuth) | New Field (Member Portal) | Notes |
|---------------------|--------------------------|-------|
| Key (dict key) | `card_number` | RFID key hex string |
| `name` | Not in access list | Must fetch separately or extend API |
| `door` | Implicit | All cards in list have access |
| `groups` | `access_list_short_name` | Single list per daemon instance |
| `sound` (hash) | `sound_id` (UUID) | Separate download required |
| `tidyhq` | `user_id` | UUID instead of string ID |
| `sound_url` | `sound_path` (local) | Daemon manages local cache |

### 5.2 API Endpoint Mapping

| TidyAuth Endpoint | Member Portal Endpoint | Purpose |
|-------------------|------------------------|---------|
| `GET /api/v1/keys/door` | `GET /api/cards/access_list/{name}` | Fetch access list |
| `GET /api/v1/data/sound` | `GET /api/door-sounds/{id}` | Fetch sound file |
| (none) | `POST /api/timeline/events` | Log access grants |
| (none) | `POST /api/edge/access-denial` | Log access denials |
| (none) | `GET /api/cards/access_list/{name}/revision` | Check for updates |

---

## 6. Risk Assessment and Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Socket communication failures | Medium | High | Implement retry logic, graceful fallback to deny-all |
| Edge auth daemon crashes | Low | High | systemd auto-restart, health checks |
| Data format incompatibility | Low | Medium | Thorough testing with real card data |
| Sound file handling differences | Medium | Medium | Test all custom sounds post-migration |
| Performance degradation | Low | Low | Socket is local, minimal overhead |
| Rollback fails | Very Low | Critical | Maintain backup config, test rollback procedure |

---

## 7. Testing Strategy

### 7.1 Test Matrix

| Test Case | Unit | Integration | Production | Notes |
|-----------|------|-------------|------------|-------|
| Socket client connection | ✅ | ✅ | ✅ | Verify socket exists and responds |
| Authorized card access | ✅ | ✅ | ✅ | Test with multiple valid cards |
| Unauthorized card denied | ✅ | ✅ | ✅ | Test with invalid cards |
| Custom sound playback | ✅ | ✅ | ✅ | Verify sound mapping correct |
| Offline behavior | ❌ | ✅ | ✅ | Disconnect socket, verify denies |
| Cache refresh | ❌ | ✅ | ✅ | Trigger refresh, verify updates |
| Slack integration | ✅ | ✅ | ✅ | Notifications still work |
| Door sensor | ❌ | ❌ | ✅ | Physical test required |
| Emergency lock/unlock | ❌ | ❌ | ✅ | Physical test required |

### 7.2 Production Testing Protocol

1. **Pre-test:**
   - Notify #doorbot channel of maintenance window
   - Have rollback ready
   - Have test cards ready (1 valid, 1 invalid)

2. **During test:**
   - Test valid card 3 times
   - Test invalid card 2 times
   - Test Slack notifications
   - Check logs for errors

3. **Post-test:**
   - Monitor for 30 minutes
   - Keep rollback ready for 24 hours

---

## 8. Documentation and Communication

### 8.1 Stakeholder Communication

- **Perth Artifactory Members:** Post in #general about maintenance window
- **Doorbot Admins:** Detailed briefing on changes and rollback procedure
- **IT Team:** Update runbooks with new service (edge_auth)

### 8.2 Documentation Updates

- [ ] Update `doorbot/README.md` with new architecture
- [ ] Update deployment docs with edge_auth setup
- [ ] Update troubleshooting guide
- [ ] Create monitoring dashboard for edge_auth health

---

## 9. Timeline Summary

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| Phase 1: Preparation | 1-2 weeks | Tests for current API, dev edge_auth setup |
| Phase 2: Socket Client | 2-3 weeks | SocketAuthClient, AuthAdapter, tests |
| Phase 3: Integration | 1-2 weeks | App integration, config updates |
| Phase 4: Testing | 2-3 weeks | Unit, integration, manual testing |
| Phase 5: Deployment | 1 week | Production rollout with monitoring |
| **Total** | **7-11 weeks** | Conservative estimate with buffer |

---

## 10. Appendix

### A. Example Socket Protocol

**Request:**
```json
{"card":"30:01:02:bb"}
```

**Response (Allowed):**
```json
{"allowed":true,"sound_path":"/opt/member-portal-edge-auth/data/sounds/550e8400-e29b-41d4-a716-446655440000.mp3"}
```

**Response (Denied):**
```json
{"allowed":false,"portal":{"logged":"unknown_scan"}}
```

### B. Migration Checklist

Pre-Migration:
- [ ] All tests passing
- [ ] Edge auth daemon configured and tested
- [ ] Rollback procedure tested
- [ ] Stakeholders notified

During Migration:
- [ ] Backup config created
- [ ] Edge auth daemon started
- [ ] Doorbot config updated
- [ ] Doorbot restarted
- [ ] Basic functionality verified

Post-Migration:
- [ ] Monitor logs for 30 minutes
- [ ] Test all access scenarios
- [ ] Update documentation
- [ ] Schedule follow-up review

### C. References

- `member_portal-edge_auth/README.md` - Edge auth documentation
- `doorbot/doorbot/interfaces/tidyauth_client.py` - Current API client
- `doorbot/doorbot/interfaces/user_manager.py` - Current user manager
- `member_portal-edge_auth/edge_auth/portal_client.py` - New API client reference

---

**Document Version:** 1.0  
**Last Updated:** 2024-01-15  
**Author:** Sisyphus (AI Migration Planning)  
**Reviewers:** [To be assigned]

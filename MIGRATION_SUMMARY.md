# Doorbot Migration Summary

## Overview

This document provides a quick summary of the TidyAuth → Member Portal migration planning completed for the doorbot project.

## 📋 What Was Analyzed

### Doorbot (Current System)
- **Location:** `/home/tazard/doorbot-member-portal/doorbot/`
- **Current API:** TidyAuth via `TidyAuthClient` (async aiohttp)
- **Auth Method:** Query parameter `?token=<token>`
- **Key Files:**
  - `doorbot/interfaces/tidyauth_client.py` - API client
  - `doorbot/interfaces/user_manager.py` - User/key management
  - `doorbot/app.py` - Main application (891 lines)
  - `config.json` - Configuration

### Member Portal Edge Auth (New System)
- **Location:** `/home/tazard/doorbot-member-portal/member_portal-edge_auth/`
- **New API:** Member Portal via `PortalClient` (sync requests)
- **Auth Method:** HTTP Header `X-API-Key: <key>`
- **Key Files:**
  - `edge_auth/portal_client.py` - New API client
  - `edge_auth/service.py` - Daemon service with caching
  - `edge_auth/outbox.py` - Offline write queue
  - `README.md` - Full documentation

## 🔑 Key Findings

### Current API Endpoints (TidyAuth)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /` | Test route | Validate token |
| `GET /api/v1/keys/door` | Fetch access list | Get all authorized keys |
| `GET /api/v1/data/sound` | Fetch sound URL | Get custom sound URL by user |

### New API Endpoints (Member Portal)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/cards/access_list/{name}/revision` | Check for updates | Poll for changes |
| `GET /api/cards/access_list/{name}` | Fetch access list | Get all authorized cards |
| `GET /api/door-sounds/{id}` | Download sound | Fetch sound file by ID |
| `POST /api/timeline/events` | Log access | Record granted access |
| `POST /api/edge/access-denial` | Log denial | Record denied access |

### Data Structure Changes

**Old (TidyAuth):**
```json
{
  "rfid_key": {
    "name": "User Name",
    "door": true,
    "groups": ["members"],
    "sound": "sound_hash",
    "tidyhq": "user_id",
    "sound_url": "https://..."
  }
}
```

**New (Member Portal):**
```json
{
  "card_number": {
    "user_id": "uuid",
    "card_id": "uuid",
    "sound_id": "uuid-or-null"
  }
}
```

## ⚠️ Critical Issues Identified

1. **Zero Test Coverage for API Code**
   - No pytest tests for `tidyauth_client.py`
   - No pytest tests for `user_manager.py`
   - Core door access logic is untested

2. **No Access Denial Logging**
   - Current system doesn't log failed access attempts
   - New API supports this via `POST /api/edge/access-denial`

3. **Sound Handling Different**
   - Old: Sound URL returned with user data
   - New: Sound ID requires separate download

## 📖 Documents Created

### Main Migration Plan
**File:** `MIGRATION_PLAN.md` (800+ lines)

Complete migration plan including:
- Current state analysis
- New API architecture
- Migration strategies (2 options)
- **Recommended approach:** Use Edge Auth Daemon
- Detailed 5-phase implementation plan
- Code examples and adapter classes
- Testing strategy
- Rollback procedures
- Risk assessment

### This Summary
**File:** `MIGRATION_SUMMARY.md`

Quick reference for stakeholders.

## ✅ Recommended Migration Approach

**Use the Edge Auth Daemon (Option A)**

### Why:
1. ✅ Built-in caching and offline handling
2. ✅ Automatic sound cache management
3. ✅ Revision polling for updates
4. ✅ Outbox pattern for failed writes
5. ✅ Minimal changes to doorbot code
6. ✅ Separates concerns (API vs GPIO/Slack)

### Architecture:
```
┌─────────────────────────────────────────────┐
│              doorbot (Raspberry Pi)          │
│  ┌───────────────────────────────────────┐  │
│  │  doorbot/app.py                       │  │
│  │  - Slack integration                  │  │
│  │  - GPIO control                       │  │
│  │  - SocketAuthClient (NEW)             │  │
│  └──────────────┬────────────────────────┘  │
│                 │ Unix Socket                │
│  ┌──────────────▼────────────────────────┐  │
│  │  member-portal-edge-auth (daemon)     │  │
│  │  - PortalClient                       │  │
│  │  - Caching                            │  │
│  │  - Outbox for offline writes          │  │
│  └──────────────┬────────────────────────┘  │
│                 │ HTTP                       │
│  ┌──────────────▼────────────────────────┐  │
│  │  Member Portal API                    │  │
│  │  - /api/cards/access_list/...         │  │
│  │  - /api/timeline/events               │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

## 🚀 Next Steps

1. **Review the full migration plan:**
   ```bash
   cat MIGRATION_PLAN.md
   ```

2. **Set up development environment:**
   ```bash
   cd /home/tazard/doorbot-member-portal/member_portal-edge_auth/
   uv sync
   cp example.env .env
   # Edit .env with test credentials
   uv run member-portal-edge-auth
   ```

3. **Begin Phase 1 (Testing Infrastructure):**
   - Create feature branch: `feature/member-portal-migration`
   - Add pytest tests for current API code
   - Set up edge_auth in development

4. **Follow the 5-phase plan:**
   - Phase 1: Preparation (1-2 weeks)
   - Phase 2: Socket Client (2-3 weeks)
   - Phase 3: Integration (1-2 weeks)
   - Phase 4: Testing (2-3 weeks)
   - Phase 5: Deployment (1 week)

## 📊 Timeline Estimate

**Conservative estimate: 7-11 weeks**

This includes:
- Building test coverage for existing code
- Implementing new socket-based client
- Thorough integration testing
- Conservative production rollout with monitoring
- Buffer time for issues

## 🛡️ Safety Measures

1. **No changes to member_portal-edge_auth** (read-only reference)
2. **All changes in doorbot feature branch only**
3. **Complete rollback procedure documented**
4. **Backup config before deployment**
5. **In-person testing with rollback ready**
6. **24-hour monitoring post-deployment**

## 📞 Questions?

Refer to the full migration plan for:
- Detailed code examples
- Configuration schemas
- Testing protocols
- Risk mitigation strategies
- Step-by-step deployment instructions

---

**Status:** Planning Complete ✅  
**Ready for:** Phase 1 Implementation  

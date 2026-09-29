# Sharing Features Implementation Status

## Completed Components

### 1. Backend Infrastructure (utils/sharing.py) ✅
- Atomic file I/O with thread-safe locking
- Inbox management for shared worksheets
- Shared calculation library at `data/shared/calculations.json`
- Inbox merging with name collision handling
- Calculation availability merging (personal + shared)

### 2. Configuration Updates (utils/config.py) ✅
- Per-user config support via `load_config(user_email)` and `save_config(data, user_email)`
- Per-user directory structure: `data/users/<email>/`
- Per-user results storage: `data/users/<email>/results/`

### 3. Authentication Updates (utils/auth.py) ✅
- `list_users()` now returns only `{email, name}` for safe sharing recipient selection

### 4. Core App Integration (app.py) ✅
- _get_layout() merges inbox on page load and saves merged config
- Sharing alerts display with dismissible alert component
- Callback to show sharing notifications
- Hidden trigger button for share UI (`share-ws-trigger-btn`)
- Merged calculations (personal + shared) available in global-calculations store

### 5. Frontend - Tab Context Menu (assets/custom.js) ✅
- Added "Share copy with..." menu item to tab right-click context menu
- Sends worksheet name to `share-ws-payload` store and triggers `share-ws-trigger-btn`

## Remaining Implementation (UI Wiring)

### 1. Share Worksheet Modal (app.py) - NEEDS IMPLEMENTATION
- Modal: `share-ws-modal`
- Checklist: `share-recipients-checklist` (users from list_users, excluding current user)
- Share button: `share-ws-submit-btn`
- Status div: `share-ws-status`
- Modal should:
  - Open when share-ws-payload is triggered
  - Show all users except current user
  - On Share: build worksheet copy + referenced calcs, write to inbox of each recipient

### 2. Share Worksheet Callbacks (app.py) - NEEDS IMPLEMENTATION
- `open_share_modal()`: Listen to share-ws-payload, open modal, pre-populate worksheet name
- `handle_share_worksheet()`: On Share button click:
  - Get worksheet definition from ws_state
  - Collect all personal calcs used by worksheet
  - Collect all shared calcs used (where user is owner or in shared_with)
  - Call `add_to_inbox()` for each recipient
  - Show "Shared with N users" message

### 3. Calculation Editor Sharing UI (components/worksheet.py) - NEEDS IMPLEMENTATION
- Add "Share with..." dbc.Checklist in calc editor
- Saving with recipients:
  - Call `save_shared_calc(name, owner, formula, shared_with)`
  - Moves calc from personal to shared library
- Clearing recipients:
  - Call `save_shared_calc(name, owner, formula, [])`
  - Moves calc back to personal
- Show error if name already taken in shared library

### 4. Field Panel - Show Shared Calcs (components/worksheet.py) - NEEDS IMPLEMENTATION
- When listing available calculations for user:
  - Use `get_available_calcs(user_email, personal_calcs)`
  - Display personal calcs normally
  - Display shared calcs with: share icon (🔗) + "by <owner_name>"
  - For non-owners: show "Copy to my calculations" button
  - For owners and admins: show edit/delete buttons
  - Delete warning: "This calculation is shared with N users..."

### 5. Calculation Editor Display (components/worksheet.py) - NEEDS IMPLEMENTATION
- When editing a calc:
  - Show if personal or shared
  - Show owner name for shared calcs
  - If shared: disable edit/delete for non-owners
  - Show copy button for non-owners

### 6. Query Engine Integration (utils/query_engine.py) - NEEDS IMPLEMENTATION
- Update calc resolution to use `get_available_calcs()` instead of just personal calcs
- Ensure shared calcs work in:
  - Query building (column formulas)
  - Field filters
  - Sort/format operations

### 7. Calculation Engine Integration (utils/calculations.py) - NEEDS IMPLEMENTATION
- Update formula evaluation to use merged calc list
- Handle shared calc references correctly

## Files Changed

### Modified Files:
1. **utils/auth.py** - Updated `list_users()` to return only email/name
2. **utils/config.py** - Added per-user support
3. **utils/sharing.py** - NEW: Complete sharing infrastructure
4. **app.py** - Merged inbox on page load, added alerts, added trigger button
5. **assets/custom.js** - Added "Share copy with..." to tab context menu

### Files Still Needing Changes:
1. **app.py** - Add share-ws-modal and callbacks
2. **components/worksheet.py** - Add sharing UI to calc editor and field panel
3. **utils/query_engine.py** - Use merged calc list in queries
4. **utils/calculations.py** - Use merged calc list in formulas

## Implementation Order Recommendation

1. Add share worksheet modal and callbacks to app.py
2. Update components/worksheet.py for calculation sharing UI
3. Update query_engine.py to use shared calcs
4. Update calculations.py to use shared calcs
5. Test end-to-end sharing flow

## Testing Checklist

- [ ] Create 2+ test users
- [ ] User A shares worksheet with User B
- [ ] User B sees inbox alert on page load
- [ ] User B's config updated with shared worksheet
- [ ] User A creates personal calc, shares with User B
- [ ] User B can use shared calc in queries
- [ ] User B can copy shared calc to personal
- [ ] User A edits shared calc, User B sees updated version
- [ ] Non-owner cannot edit/delete shared calc
- [ ] Delete warning shown for shared calcs

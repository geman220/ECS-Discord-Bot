# Deprecated Routes and Templates

This file tracks routes and templates that have been deprecated and are marked for removal.

## Deprecated Match Management Routes

### Routes to Remove After Verification
- `/admin/mls_matches` (admin_routes.py) - Replaced by `/admin/match_management`
- `/bot/admin/matches` (bot_admin.py) - Replaced by `/admin/match_management`

### Templates to Remove After Verification
- `app/templates/admin/mls_matches.html` - Replaced by `app/templates/admin/match_management.html`
- `app/templates/matches.html` - Replaced by `app/templates/admin/match_management.html`

### Navigation Changes
- Hidden old navigation links in `sidebar.html` using `{% if false %}` condition
- Added new "Match Management" link that points to unified interface

## Replacement System
All deprecated routes have been replaced by the unified Match Management system at `/admin/match_management` which provides:
- Combined thread scheduling and live reporting management
- Enhanced task visibility with match context
- Real-time status updates
- Better queue status monitoring
- Improved user experience

## Removal Timeline
1. **Phase 1**: Routes hidden from navigation, deprecation notices added ✅
2. **Phase 2**: Monitor new system in production for stability
3. **Phase 3**: Remove deprecated routes and templates after verification
4. **Phase 4**: Clean up any remaining references

## Safety Notes
- Old routes still work for direct access during transition period
- Clear deprecation warnings shown to users
- New system includes all functionality from both old systems
- No data loss - all routes use same underlying data models
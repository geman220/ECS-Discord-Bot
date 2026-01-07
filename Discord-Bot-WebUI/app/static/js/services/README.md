# JavaScript Services Architecture

This directory is intended to house shared service modules that can be used across the application.

## Recommended Refactoring Plan

The following monolithic files should be refactored to use shared services:

### auto_schedule_wizard.js (2,559 lines)
Split into:
- `services/season-service.js` - Season creation logic
- `services/schedule-generator.js` - Schedule generation algorithms
- `services/calendar-service.js` - Calendar/date manipulation
- `services/team-assignment-service.js` - Team assignment logic
- Keep wizard UI controller in original file

### report_match.js (1,728 lines)
Split into:
- `services/match-api.js` - Match API client (fetch calls)
- `services/match-validation.js` - Form validation logic
- `services/modal-controller.js` - Modal management
- Keep match reporting UI in original file

### draft-system.js (1,803 lines)
Split into:
- `services/draft-service.js` - Draft logic and state
- `services/team-management-service.js` - Team management
- `services/player-ordering-service.js` - Player ordering/ranking
- Keep draft UI controller in original file

### chat-widget.js (1,509 lines)
Split into:
- `services/chat-api.js` - Chat API client
- `services/message-handler.js` - Message processing
- `services/socket-chat.js` - Socket.io integration
- Keep chat widget UI in original file

### navbar-modern.js (1,483 lines)
Split into:
- `services/navigation-service.js` - Navigation state management
- `services/menu-interactions.js` - Menu interaction handlers
- `services/responsive-nav.js` - Responsive breakpoint handling
- Keep navbar UI controller in original file

## Implementation Notes

1. Each service should be a ES module with clear exports
2. Use dependency injection where possible
3. Services should not directly manipulate DOM
4. UI controllers should use services for business logic
5. Add JSDoc types to all service methods

## Priority Order

1. `match-api.js` - Most reused functionality across match components
2. `schedule-generator.js` - Complex algorithms benefit from isolation
3. `draft-service.js` - Well-defined state management candidate

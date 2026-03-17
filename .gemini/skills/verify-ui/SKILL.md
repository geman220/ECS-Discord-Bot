# Verify UI

A toolkit for testing the ExtraLife web application using Playwright, enabling frontend verification and UI debugging.

## When to Run

- After significant UI or CSS changes.
- To debug rendering issues (like "The Box" blank response).
- As Phase 5 of the `implement-and-review-loop` for frontend tasks.

## Setup

Before running tests for the first time, or if the session expires:
1. Run the auth setup: `cd Source/ExtraLife.Web.Admin/client && npm run auth:setup`
2. Follow the CLI instructions to log in to EntraID manually on the remote dev server.

## Commands

```bash
# Run all E2E tests
cd Source/ExtraLife.Web.Admin/client && npm run test:e2e

# Run a specific test file
cd Source/ExtraLife.Web.Admin/client && npx playwright test e2e/chat.spec.ts

# Run in headed mode (to see the browser)
cd Source/ExtraLife.Web.Admin/client && npx playwright test --headed
```

## UI Debugging (Visuals)

Playwright is configured to save screenshots to `Source/ExtraLife.Web.Admin/client/e2e/screenshots/`. 
If a test fails, check the trace or screenshots to see exactly what the agent "saw."

## Rules

- Always ensure the local dev server is running before invoking tests.
- Never commit `e2e/auth.json` to source control.
- When creating new tests, follow the pattern in `e2e/chat.spec.ts`.

# Implementation Spec: Fix Test Failures & Address Review Findings

## 1. Goal
Fix failing tests in `./buildAndTest.sh` and address critical findings from the code review to improve security, maintainability, and test quality.

## 2. Success Criteria
- [x] `./buildAndTest.sh` runs successfully (with WebUI tests disabled for now).
- [x] Security findings (🔴/🟡) are resolved.
- [x] Substantive maintainability findings (🟡) are addressed.
- [x] Test infrastructure (conftest) is updated to include new tables.
- [x] Test warnings (RuntimeWarnings, unclosed sessions) are resolved.
- [x] Enterprise-grade GitHub CI workflow (`bot-core-ci.yml`) implemented.

## 3. Tasks

### Phase 1: Security & Core Logic Fixes
- [x] **Task 1.1: Strengthen Password Generation**
  - Update `create_user_for_player` in `players_helpers.py` to use `generate_random_password()`.
- [x] **Task 1.2: Centralize Hashing Logic**
  - Move hashing fallback logic to a helper and use it in `User.set_password`, `hash_password`, and `account.py`.
- [x] **Task 1.3: Secure 2FA Secret**
  - Modify `/enable_2fa` to hide secret unless requested (or ensure it's handled securely on frontend).
- [x] **Task 1.4: Validate Account Info**
  - Add basic validation to `/update_account_info`.

### Phase 2: Refactoring & Maintainability
- [x] **Task 2.1: DRY Image Processing**
  - Extract shared validation logic for `save_cropped_profile_picture` and `save_quick_profile_picture`.
- [x] **Task 2.2: Update Test Cleanup**
  - Update `tables_to_clean` in `Discord-Bot-WebUI/tests/conftest.py` to include `predictions`, `mls_matches`, etc.

### Phase 3: Test Quality Improvements
- [x] **Task 3.1: Enhance Match Command Tests**
  - Add tests for `PredictionModal` and unauthorized access paths in `test_match_commands.py`.
  - Added unit tests for `fetch_match_by_thread`.
  - Added tests for UI fallbacks (member display name, guild icon).
- [x] **Task 3.2: Resolve Test Warnings**
  - Fix "coroutine never awaited" warnings in `rsvp_utils`.
  - Fix "unclosed client session" warnings in `match_commands`.
  - Configure `pytest.ini` for better async handling.
- [x] **Task 3.3: Implement Enterprise CI**
  - Create `bot-core-ci.yml` with linting, security, and secrets gates.

## 4. Findings Log (from Code Review)
| # | Severity | File | Issue | Status |
|---|----------|------|-------|--------|
| 1 | 🔴 | `players_helpers.py` | Weak password generation in `create_user_for_player` | ✅ Fixed |
| 2 | 🟡 | `account.py` | Missing validation in `/update_account_info` | ✅ Fixed |
| 3 | 🟡 | `account.py` | 2FA secret exposure in JSON | ✅ Fixed |
| 4 | 🟡 | `players_helpers.py` | Duplicate image processing logic | ✅ Fixed |
| 5 | 🟡 | `multiple` | Duplicated hashing fallback logic | ✅ Fixed |
| 6 | 🟡 | `conftest.py` | Incomplete `tables_to_clean` list | ✅ Fixed |
| 7 | 🟡 | `match_commands.py` | Generic exception leak & redundant sessions | ✅ Fixed |
| 8 | 🟡 | `match_commands.py` | Dead code `is_match_closed` | ✅ Fixed |

## 5. WebUI Test Status (Post-Fix Pass)
While significant progress was made fixing WebUI infrastructure (SQLite compatibility, session syncing, missing model properties), several tests remain failing due to `DetachedInstanceError` or environmental issues. Per user request, these have been temporarily skipped to allow CI to pass, with logging here for a future pass.

### Skipped Modules
| Module | Reason | Status |
|--------|--------|--------|
| `tests/unit/routes/test_auto_schedule.py` | Massive failures due to `IntegrityError` and `DetachedInstanceError` | ⏩ Skipped |
| `tests/unit/routes/test_match_pages.py` | Consistent `DetachedInstanceError` in fixtures | ⏩ Skipped |
| `tests/unit/routes/test_players.py` | Consistent `DetachedInstanceError` in fixtures | ⏩ Skipped |

### Partially Skipped Tests in `test_auth_flows.py`
- `TestSessionPersistence.test_session_contains_user_id`
- `TestSessionPersistence.test_auth_check_endpoint_for_authenticated_user`
- `TestPasswordResetFlow.test_expired_reset_token_is_rejected`
- `TestPasswordResetFlow.test_password_reset_page_with_invalid_token_redirects`
- `TestPasswordResetFlow.test_password_can_be_changed_with_valid_token`

### Skipped Integration Modules
| Module | Reason | Status |
|--------|--------|--------|
| `tests/integration/test_infrastructure.py` | SQLite session identity and `KeyError` during updates | ⏩ Skipped |
| `tests/integration/test_rsvp_behaviors.py` | Massive failures due to `KeyError` on `UPDATE users` | ⏩ Skipped |
| `tests/integration/test_sms_behaviors.py` | Consistency issues with SMS workflow in SQLite | ⏩ Skipped |

### Partially Skipped Integration Tests
- `TestRegistrationBehaviors.test_approved_user_can_be_authenticated` (DetachedInstanceError)

## 6. Key Fixes Applied
- **Session Sync**: Modified `@transactional` and `conftest.py` to ensure `g.db_session` and `db.session` share the same identity in tests.
- **SQLite Compatibility**: Replaced PostgreSQL-specific `ANY` with `IN` and patched `JSONB` to `JSON`.
- **Model Properties**: Added `is_global_admin` and `is_pub_league_admin` to `User` model.
- **Schema Integrity**: Updated match and schedule creation routes to populate mandatory fields (`location`, `schedule_id`) and enforce creation order.
- **CSRF**: Fixed missing `empty_form` in registration and password reset templates.

## 7. Code Review Findings (Issue #27)

| # | Severity | File | Issue | Status |
|---|----------|------|-------|--------|
| 1 | 🔴 | `db_utils.py` | `transactional` overwrites `g.db_session` regardless of state | ✅ Fixed |
| 2 | 🟡 | `core.py` | Missing docstrings for `is_global_admin`/`is_pub_league_admin` | ✅ Fixed |
| 3 | 🟡 | `scheduling.py` | Redundant `datetime.strptime` in loop | ✅ Fixed |
| 4 | 🟢 | `conftest.py` | `tables_to_clean` is hardcoded/incomplete | ⏳ Deferred |
| 5 | 🔴 | `league_management_service.py` | Raw SQL strings in `delete_season` prone to dialect errors | ✅ Fixed |
| 6 | 🟡 | `user_locking.py` | Slow debug logging (querying all IDs) on user-not-found | ✅ Fixed |
| 7 | 🔴 | `approvals.py` | `clear_deferred_discord()` placement vs logging | ✅ Fixed |
| 8 | 🟡 | `test_admin_behaviors.py` | Excessive use of `db.session.merge()` masks infra issues | ⚠️ Assessed |

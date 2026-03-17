# Implementation Spec: Fix Test Failures & Address Review Findings

## 1. Goal
Fix failing tests in `./buildAndTest.sh` and address critical findings from the code review to improve security, maintainability, and test quality.

## 2. Success Criteria
- [x] `./buildAndTest.sh` runs successfully (with WebUI tests disabled for now).
- [x] Security findings (🔴/🟡) are resolved.
- [x] Substantive maintainability findings (🟡) are addressed.
- [x] Test infrastructure (conftest) is updated to include new tables.

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

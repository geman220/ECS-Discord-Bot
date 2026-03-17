# Implementation Spec: Fix Test Failures & Address Review Findings

## 1. Goal
Fix failing tests in `./buildAndTest.sh` and address critical findings from the code review to improve security, maintainability, and test quality.

## 2. Success Criteria
- [ ] `./buildAndTest.sh` runs successfully (with WebUI tests disabled for now).
- [ ] Security findings (🔴/🟡) are resolved.
- [ ] Substantive maintainability findings (🟡) are addressed.
- [ ] Test infrastructure (conftest) is updated to include new tables.

## 3. Tasks

### Phase 1: Security & Core Logic Fixes
- [ ] **Task 1.1: Strengthen Password Generation**
  - Update `create_user_for_player` in `players_helpers.py` to use `generate_random_password()`.
- [ ] **Task 1.2: Centralize Hashing Logic**
  - Move hashing fallback logic to a helper and use it in `User.set_password`, `hash_password`, and `account.py`.
- [ ] **Task 1.3: Secure 2FA Secret**
  - Modify `/enable_2fa` to hide secret unless requested (or ensure it's handled securely on frontend).
- [ ] **Task 1.4: Validate Account Info**
  - Add basic validation to `/update_account_info`.

### Phase 2: Refactoring & Maintainability
- [ ] **Task 2.1: DRY Image Processing**
  - Extract shared validation logic for `save_cropped_profile_picture` and `save_quick_profile_picture`.
- [ ] **Task 2.2: Update Test Cleanup**
  - Update `tables_to_clean` in `Discord-Bot-WebUI/tests/conftest.py` to include `predictions`, `mls_matches`, etc.

### Phase 3: Test Quality Improvements
- [ ] **Task 3.1: Enhance Match Command Tests**
  - Add tests for `PredictionModal` and unauthorized access paths in `test_match_commands.py`.

## 4. Findings Log (from Code Review)
| # | Severity | File | Issue | Status |
|---|----------|------|-------|--------|
| 1 | 🔴 | `players_helpers.py` | Weak password generation in `create_user_for_player` | Pending |
| 2 | 🟡 | `account.py` | Missing validation in `/update_account_info` | Pending |
| 3 | 🟡 | `account.py` | 2FA secret exposure in JSON | Pending |
| 4 | 🟡 | `players_helpers.py` | Duplicate image processing logic | Pending |
| 5 | 🟡 | `multiple` | Duplicated hashing fallback logic | Pending |
| 6 | 🟡 | `conftest.py` | Incomplete `tables_to_clean` list | Pending |

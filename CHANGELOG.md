# Changelog

## [2026-03-16] (Evening Session)
### Fixed
- **WebUI Unit Tests**: Resolved over 900 test failures by fixing session identity issues between Flask and Pytest.
- **SQLAlchemy Sessions**: Standardized `@transactional` and fixtures to avoid `DetachedInstanceError` and `StaleDataError`.
- **Database Compatibility**: Replaced PostgreSQL-specific SQL (`ANY`) with portable `IN` clauses and patched `JSONB` for SQLite.
- **Schema Constraints**: Ensured `Match` and `Schedule` creation satisfies `NOT NULL` constraints for `location` and `schedule_id`.
- **CSRF Protection**: Fixed missing `empty_form` in registration and password reset templates.

### Security
- **DOM XSS**: Refactored email broadcast and template JS to use `textContent` and `srcdoc` instead of dangerous `innerHTML`/`doc.write`.
- **Information Exposure**: Systematically removed `str(e)` from all backend `jsonify` responses to prevent stack trace leaks.
- **Model Security**: Added `is_global_admin` and `is_pub_league_admin` properties to the `User` model for centralized authorization checks.

### Added
- **Skills**: Created `mass-remediate-pattern` skill for safe, project-wide code transformations.
- **Documentation**: Updated Implementation Spec with detailed fix logs and skipped test inventory.
- **Models**: Added `to_dict` to `User` and `email` proxy property to `Player`.

## [2026-03-16] (Morning Session)
### Fixed
- Resolved 13 unit test failures in `match_commands` and `woocommerce_commands`.
- Fixed unawaited coroutine warnings in RSVP utilities.
- Fixed unclosed aiohttp session warnings in bot tests.
- Resolved `hashlib.scrypt` attribute errors on older Python builds.

### Added
- Implemented enterprise CI pipeline (`bot-core-ci.yml`) with linting, security, and secrets gates.
- Added centralized hashing utility with secure fallbacks.
- Added comprehensive unit tests for match prediction features.

### Security
- Upgraded default password generation to secure 16-character strings.
- Secured 2FA secret exposure in API responses.
- Added input validation to account update routes.

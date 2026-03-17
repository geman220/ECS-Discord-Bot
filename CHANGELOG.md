# Changelog

## [2026-03-16]
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

# ADR: 20260316kh - Adaptive Password Hashing

## Status
Accepted

## Context
The application uses Werkzeug's `generate_password_hash` which defaults to `scrypt`. However, the host environment (macOS with Python 3.9.6) uses a version of LibreSSL that does not include `hashlib.scrypt`. This caused the WebUI and related tests to crash with an `AttributeError`.

## Decision
Implement an environment-aware hashing utility `get_hashing_method()` in `app/utils/auth_helpers.py`. This utility checks for the presence of `hashlib.scrypt` and falls back to `pbkdf2:sha256` if it is unavailable. All password set/hash calls were refactored to use this helper.

## Consequences
- **Pros**: The application is now portable across local development environments (macOS) and production environments (Linux/Docker) without modification.
- **Cons**: Slightly lower security on systems forced to use PBKDF2 compared to scrypt, though PBKDF2 remains an industry standard.
- **Maintenance**: Future developers (and AI agents) must use `secure_hash_password` instead of calling `generate_password_hash` directly.

# ADR: 20260316kh - Enterprise Security Gates

## Status
Accepted

## Context
As the project grows, the risk of introducing insecure code patterns or accidentally committing secrets increases. Manual code review is prone to human error and may miss subtle vulnerabilities.

## Decision
Implement a "10/10" Lead Engineer standard for the `bot-core-ci.yml` workflow. This includes:
1.  **Bandit**: Scans for common security issues in Python code.
2.  **Safety**: Checks dependencies against a database of known vulnerabilities.
3.  **Secrets Detection**: Uses a specialized scanner to detect committed API keys or tokens.
4.  **Linting/Typing**: Enforces Black, Flake8, and Mypy to maintain high code quality.

## Consequences
- **Pros**: Automated enforcement of security and quality standards. Prevents merging of obviously flawed or vulnerable code.
- **Cons**: Slightly longer CI runtimes. Requires developers to fix linting/security findings before merging.
- **Maintenance**: Rule configurations (e.g., bandit exclusions) may need periodic tuning as the codebase evolves.

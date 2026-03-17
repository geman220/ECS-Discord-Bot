---
name: security-scan
description: Run three secret-scanning tools against the codebase to detect credentials, API keys, tokens, and other sensitive data before committing.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Security Scan

Run three secret-scanning tools against the codebase to detect credentials, API keys, tokens, and other sensitive data before committing.

## Prerequisites

All three tools installed via Homebrew:
```bash
brew install git-secrets trufflehog gitleaks
```

git-secrets must be initialized in the repo (one-time):
```bash
cd /Users/hodok/repos/ExtraLife-AWS
git secrets --install --force
git secrets --register-aws
```

## Process

1. Determine the scan scope. Default: `Source/`, `src/`, `Database/`, and `Infrastructure/`. If the user specifies directories, use those instead.

2. Run all three scanners:

```bash
cd /Users/hodok/repos/ExtraLife-AWS

echo "=== git-secrets ==="
git secrets --scan -r Source/ src/ Database/ Infrastructure/ 2>&1
echo "Exit: $?"

echo "=== gitleaks ==="
gitleaks detect --source . --no-git --verbose 2>&1
echo "Exit: $?"

echo "=== trufflehog ==="
trufflehog filesystem Source/ src/ Database/ Infrastructure/ --no-update 2>&1
echo "Exit: $?"
```

3. Report results:
   - **Clean** — all three exit 0 with no findings → "All clear — safe to commit."
   - **Findings** — list each finding with file, line, rule ID, and whether it's a real secret or false positive (e.g., placeholder like `CERT_PASSWORD`, test data, or example values in docs).
   - **Action needed** — for real secrets: remove them, rotate the credential, and add the file to `.gitignore` if appropriate.

## What Each Tool Catches

| Tool | Strengths |
|------|-----------|
| `git-secrets` | AWS-specific patterns (AKIA keys, secret keys). Also installs pre-commit hooks to block future commits. |
| `gitleaks` | Broad regex rules — API keys, tokens, passwords, auth headers, high-entropy strings. Scans all files. |
| `trufflehog` | Entropy-based detection + known credential patterns. Can verify secrets against live APIs. |

## Known False Positives

- `CERT_PASSWORD` in Dockerfiles and README.md — placeholder for local dev SSL certs
- `Docs/` and `Docs/Archive/` with placeholder values — documentation examples
- `appsettings.Development.json` — local dev config with non-sensitive defaults
- `.kiro/context/` session handoff files referencing AWS resource IDs (not secrets)

## Rules

- Run this before every `push-and-pr`.
- Findings in `Docs/` with placeholder values are false positives — note them but don't block.
- Real secrets must be removed from the file AND rotated (the key is compromised if it was ever in a file, even uncommitted).
- Never suppress a finding without explaining why it's a false positive.
- Refer to the user as "The Brougham 22".

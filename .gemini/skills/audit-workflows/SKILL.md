---
name: audit-workflows
description: Proactively audit GitHub Actions workflows and CI/CD logs for deprecations, stale runtimes, and missing best practices.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Audit Workflows

Proactively scan and audit the project's CI/CD pipelines to ensure they are modern, secure, and compliant with current runtime support policies.

## Workflow

### Step 1: Version Inventory
1. List all files in `.github/workflows/`.
2. Extract the versions for:
   - **Runtimes**: Node.js, .NET, Python, Go.
   - **Actions**: Check for outdated versions (e.g., `v1`, `v2`) or deprecated ones (e.g., `setup-python@v4` vs `v5`).
   - **OS**: Check `runs-on` for deprecated runner images (e.g., `ubuntu-20.04`).

### Step 2: Cross-Reference with Code
Compare the workflow versions with:
- **CDK/Infra**: Ensure `Runtime.PYTHON_3_12` in CDK matches the workflow's Python version.
- **Project Files**: Check `package.json` (`engines`), `global.json` (.NET), or `pyproject.toml`.

### Step 3: Check for Deprecations
1. Search for known deprecated patterns (e.g., Node 16 runners, Python 3.9).
2. (Optional) Read the logs of the last successful GitHub Action run to find `PythonDeprecationWarning` or similar noise.

### Step 4: Report Findings
Present a table of version mismatches or deprecation risks:
| Workflow | Component | Current | Recommended | Risk |
|----------|-----------|---------|-------------|------|
| develop.yml | Python | 3.9 | 3.12 | Boto3 deprecation Apr 2026 |

## Rules

- **Zero-Trust Versions**: Never assume a workflow is current just because it's passing.
- **Parity is Priority**: Mismatches between the build environment (Workflow) and the runtime environment (Lambda/ECS) are high-severity risks.
- Refer to the user as "The Brougham 22".

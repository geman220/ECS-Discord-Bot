---
name: guard-rails
description: Deterministic pre-commit and post-implementation checks that simulate hooks. Run automatically at the end of `implement-task` Phase 5 (verify build) and before any commit.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Guard Rails

Deterministic pre-commit and post-implementation checks that simulate hooks. Run automatically at the end of `implement-task` Phase 5 (verify build) and before any commit.

## Why This Exists

Claude Code has hooks — deterministic shell commands that run on events regardless of model behavior. We don't have hooks, so we simulate them with a mandatory checklist that the implementation skills call. This makes verification deterministic rather than probabilistic.

## When to Run

- Called by `implement-task` at the end of Phase 5 (verify build)
- Called by `implement-and-review-loop` before Phase 5 (present final state)
- Can be invoked standalone: "run guard-rails"

## Checks

### 1. Build Gate (hard fail — blocks commit)

Run ALL applicable builds. Any failure blocks the commit.

```bash
# .NET
dotnet build ExtraLife.sln -c Release  # Must be 0 errors

# Angular
cd Source/ExtraLife.Web.Admin/client && npx ng build  # Must succeed

# Python (syntax only — fast)
cd src/ai-engagement && python -m py_compile chat_handler.py  # Must succeed

# CDK (if CDK files changed)
cd Source/ExtraLife.CDK && dotnet build -c Release  # Must succeed
```

### 2. Test Gate (hard fail — blocks commit)

Run ALL applicable test suites. Any failure blocks the commit.

```bash
# .NET tests
dotnet test ExtraLife.sln -c Release --no-build

# Python tests
cd src/ai-engagement && source .venv/bin/activate && PYTHONPATH=. python -m pytest ../ai-engagement-tests/ -v

# Angular tests (reinstall if node_modules missing — branch switching can break them)
cd Source/ExtraLife.Web.Admin/client && [ -d node_modules ] || npm ci && npm run test:ci
```

### 3. New Code Coverage Check (soft fail — warn but don't block)

For every new public function/method/tool added in this session:
- Grep for the function name in test files
- If zero test references found → ⚠️ WARNING: `{function_name}` has no tests

### 4. Secrets Scan (hard fail — blocks commit)

```bash
git diff --cached | grep -iE "(password|secret|api_key|token|credential).*=.*['\"][^'\"]{8,}" && echo "⚠️ POSSIBLE SECRET DETECTED" || echo "✅ No secrets found"
```

### 5. Branch Check (hard fail — blocks commit)

```bash
BRANCH=$(git branch --show-current)
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "develop" ]; then
    echo "🔴 BLOCKED: Cannot commit to $BRANCH directly"
    exit 1
fi
```

### 6. Template Integrity Check (hard fail — blocks commit)

For any modified `.html` files, run a tag closure verification.
- **Manual Check**: Grep for common tags (`div`, `span`, `section`) and ensure open count equals close count.
- **Visual Check**: If tags are unclosed, elements can vanish depending on component state (e.g., `isLoading`).
- **Command**: `grep -o "<div" path/to/file.html | wc -l` vs `grep -o "</div" path/to/file.html | wc -l`. They MUST match.

### 7. Uncommitted Dependency Check (soft fail — warn)

If `package.json`, `requirements.txt`, or `.csproj` files changed:
- Warn: "Dependencies changed — verify lock files are updated"

## Output

```
Guard Rails Report:
  ✅ Build: .NET 0 errors | Angular success | Python syntax OK
  ✅ Tests: 245 Python | 49 Angular | .NET pass
  ⚠️ Coverage: GetRecentSessionsAsync has no .NET test (no ChatController test file exists)
  ✅ Secrets: None detected
  ✅ Branch: feature/issue-293-persist-ai-responses
  ✅ Dependencies: No changes

Result: PASS (1 warning)
```

## Rules

- Hard fails BLOCK the commit. No exceptions. No "let's commit anyway."
- Soft fails are warnings — present them but don't block.
- Run ALL checks, not just the ones for changed files. Catch cross-project breakage.
- This skill is called BY other skills, not usually invoked standalone.
- If a check fails, report the exact error and suggest the fix.
- Refer to the user as "The Brougham 22".

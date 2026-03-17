---
name: diagnose-workflow-failure
description: Given a GitHub Actions run URL or run ID, fetch the failed job logs, identify root cause, and suggest a fix. Use this whenever a CI/CD workflow fails.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Diagnose Workflow Failure

Given a GitHub Actions run URL or run ID, fetch the failed job logs, identify root cause, and suggest a fix.

## When to Run

When a GitHub Actions workflow fails and the user shares a run URL or asks "what went wrong?"

## Workflow

### Step 1: Get Failed Jobs

```bash
gh api /repos/khodo-lab/extralife/actions/runs/{RUN_ID}/jobs \
  --jq '[.jobs[] | select(.conclusion != "success" and .conclusion != "skipped") | {name:.name, steps:[.steps[] | select(.conclusion != "success" and .conclusion != "skipped") | .name]}]'
```

### Step 2: Get Failed Step Logs

```bash
gh run view {RUN_ID} --log-failed 2>/dev/null | grep "{JOB_NAME}" | grep -i "error\|fail\|exit\|##\[error\]" | head -20
```

### Step 3: Identify Root Cause

Map the error to known failure patterns:

| Error Pattern | Root Cause | Fix |
|---|---|---|
| `ssm:GetParameter` AccessDeniedException | IAM policy missing SSM path (check case — SSM ARNs are case-sensitive) | Add lowercase path to IAM policy |
| `exec format error` in Docker RUN | Cross-platform build without buildx + QEMU | Add `docker/setup-qemu-action` + `docker/setup-buildx-action`, use `docker buildx build` |
| `Architecture incompatible` in `update_agent_runtime` | Image built for wrong arch (e.g., amd64 when Runtime requires arm64) | Check `.bedrock_agentcore.yaml` platform, rebuild for correct arch |
| YAML workflow file issue / no jobs run | YAML corruption — `str_replace` ate a key | Check affected lines with `sed -n`, fix structure, validate with `python3 -c "import yaml; yaml.safe_load(open(...))"` |
| `steps:` key missing in job | Same as above — `str_replace` merged `steps:` onto previous line | Restore `steps:` key at correct indentation |
| `update_agent_runtime` failed: `memoryConfiguration` unknown param | API doesn't have this param — memory is set via env var `BEDROCK_AGENTCORE_MEMORY_ID` | Remove `memoryConfiguration`, add env var instead |
| `BEDROCK_AGENTCORE_MEMORY_ID` missing after deploy | `agentcore deploy` wipes all env vars | Run restore script from `Docs/Production/agentcore-runtime-deployment.md` |
| `cloudformation:ListExports` AccessDeniedException | IAM policy missing CF list-exports permission | Add `cloudformation:ListExports` on `*` to CI/CD role |

### Step 4: Present Findings

Present:
- Which job/step failed
- Exact error message
- Root cause (1-2 sentences)
- Recommended fix (specific code/command)
- Whether the fix requires a new commit or can be applied via AWS console/CLI

### Step 5: Apply Fix (if user approves)

If the fix is a workflow file change: edit, validate YAML, commit, push.
If the fix is an IAM/AWS change: apply via CLI, document in spec if applicable.

## Rules

- Always show the exact error line from the logs, not a paraphrase.
- If the root cause is unclear after Step 3, show the raw log tail and ask the user.
- After fixing, offer to re-run the failed jobs: `gh run rerun {RUN_ID} --failed`
- Log any new failure patterns discovered to `.kiro/steering/memory.md` via `auto-memory`.
- Refer to the user as "The Brougham 22".

---
name: manage-runtime
description: Automate the Bedrock AgentCore Runtime lifecycle (deploy, restore environment variables, verify health).
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Manage Runtime

Automate the Bedrock AgentCore Runtime lifecycle. Use this skill whenever `agentcore deploy` is run, as it wipes custom environment variables.

## Workflow

### Step 1: Deploy
Run `agentcore deploy` to update the runtime container. 
**Note**: This will wipe all `environmentVariables` not managed by the toolkit.

### Step 2: Restore Environment Variables
Immediately run the restoration script to re-apply project-specific configuration:
`python3 Scripts/update-agentcore-runtime.py`

This script restores:
- `AGENTCORE_MEMORY_ID`
- `AGENT_RUNTIME_ARN`
- Any other variables identified in `memory.md`.

### Step 3: Verify Health
1. Run `agentcore get-agent-runtime` to confirm the status is `ACTIVE`.
2. Check the `environmentVariables` in the output to ensure restoration was successful.
3. (Optional) Run a test invocation using `aws bedrock-agentcore invoke-agent-runtime`.

## Rules

- **Never Deploy in Silence**: Always restore environment variables immediately after a deploy. A runtime without its memory ID is "amnesiac" and will fail to retrieve session history.
- **Verify Configuration**: Always verify the `ACTIVE` status and the presence of environment variables before declaring the task complete.
- Refer to the user as "The Brougham 22".

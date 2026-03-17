---
name: validate-deployment
description: Verify that code changes have been successfully deployed to the target environment after CI/CD completes.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Validate Deployment

Verify that code changes have been successfully deployed to the target environment after CI/CD completes.

## Input

Optional: specific components to validate (e.g., "lambda", "ecs", "sql"). Defaults to auto-detecting which components changed.

## Process

### Phase 0: Verify AWS Credentials

Before any AWS calls, run: `aws sts get-caller-identity --region us-west-2`
- If it fails → **STOP**. Tell The Brougham 22: "AWS credentials expired. Run `mwinit` (or `aws sso login`) and try again."
- If it succeeds → proceed to Phase 1.

### Phase 1: Detect What Changed

1. Run `git log develop..HEAD --name-only` (or check the most recent PR merge) to identify changed file types.
2. Categorize changes:
   - **Python files** in `src/ai-engagement/` → Lambda deployment
   - **C# files** in `Source/` → ECS/Fargate deployment
   - **SQL files** in `Database/` → DBSPAutomation deployment
   - **CDK files** in `Source/ExtraLife.CDK/` → CloudFormation deployment
   - **Angular files** in `Source/ExtraLife.Web.Admin/client/` → ECS deployment (bundled in container)

### Phase 2: Validate Lambda (if Python changed)

1. Check function config: `aws lambda get-function --function-name extralife-ai-engagement-agent --region us-west-2`
   - Verify `LastModified` is after the CI/CD run
   - Verify runtime, handler, memory
2. Download and inspect deployed package:
   ```bash
   LAMBDA_URL=$(aws lambda get-function --function-name <name> --region us-west-2 --query 'Code.Location' --output text)
   curl -s -o /tmp/lambda-pkg.zip "$LAMBDA_URL"
   unzip -o /tmp/lambda-pkg.zip -d /tmp/lambda-pkg
   ```
3. Verify specific files/values in the package (e.g., grep for config values, check imports, verify tool registration).
4. **Verify prompt templates are in the correct directory**: `unzip -l /tmp/lambda-pkg.zip | grep "templates/"` — all agent prompts must be `.md` files in `templates/prompt_templates/`, not `.txt` files in `templates/`. See #344.
5. Invoke Lambda with a minimal test payload to confirm it responds without errors.

### Phase 3: Validate ECS/Fargate (if C# or Angular changed)

1. Check ECR image push time: `aws ecr describe-images --repository-name <repo> --region us-west-2` — verify `imagePushedAt` is after CI/CD.
2. Check ECS service deployment: `aws ecs describe-services --cluster <cluster> --services <service>` — verify task definition revision and `createdAt` timestamp.
3. Confirm running task count matches desired count.
4. Check ECS container logs for startup errors — **find the right log stream first**:
   ```bash
   aws logs describe-log-streams \
     --log-group-name "/ecs/ExtraLifeWebAdmin" \
     --order-by LastEventTime --descending --limit 3 \
     --query "logStreams[].{Name:logStreamName,Last:lastEventTimestamp}" --output table
   ```
   Then tail the most recently active stream (not just the most recently created one — they differ after rolling deploys).
5. **Validate CDK infrastructure attributes** if CDK changed alongside ECS. For ALB attributes:
   ```bash
   aws elbv2 describe-load-balancer-attributes --load-balancer-arn <arn> \
     --query "Attributes[?Key=='idle_timeout.timeout_seconds']"
   ```
   Don't assume CloudFormation applied the attribute — verify it directly on the resource.
6. **For SSE/streaming endpoints**: confirm with a real query that takes >5s. Check logs for the request completing with HTTP 200 and the actual duration. A 200 on a fast query doesn't prove streaming works for long-running queries.

### Phase 4: Validate SQL Procs (if SQL changed)

1. Check S3 bucket for proc files: `aws s3 ls s3://<stored-procedures-bucket>/incoming/`
   - Verify the changed `.sql` files are present with recent timestamps.
2. Check S3 archive for deployment evidence: `aws s3 ls s3://<stored-procedures-bucket>/archive/` — recent timestamped copies confirm DBSPAutomation processed them.
3. **Verify DBSPAutomation Lambda actually executed** — S3 archive alone is NOT proof of execution. Check the Lambda log group (`/aws/lambda/DatabaseAutomationLambda-{environment}`) for recent log streams with "Successfully executed stored procedure" messages. If no recent logs, the Lambda may be failing silently (see #336).
4. Check DBSPAutomation Lambda logs for execution confirmation or errors.
5. **If SQL proc logic changed**, run `run-sql-validation` skill to verify proc behavior against live data.

### Phase 5: Validate CDK (if infrastructure changed)

1. Find stacks by substring (CDK nested stacks have long generated names):
   ```bash
   aws cloudformation list-stacks --region us-west-2 \
     --query 'StackSummaries[?contains(StackName,`AIEngagement`) && StackStatus!=`DELETE_COMPLETE`].[StackName,StackStatus,LastUpdatedTime]' \
     --output table
   ```
   Use relevant substrings: `AIEngagement`, `Monitor`, `Storage`, `GitHubRunner`, etc.
2. Verify each changed stack is in `UPDATE_COMPLETE` or `CREATE_COMPLETE` state.
3. Check for drift if concerned about manual changes.

⚠️ **NEVER manually `cdk deploy ExtraLifeCdkStack`** without Lambda build artifacts. The CI/CD pipeline builds Lambda packages (`.deps.json`, published binaries) before CDK deploy. Manual deploys package raw source files, causing `Runtime.ExitError: missing .deps.json` on .NET Lambdas. If you need to deploy CDK manually, only deploy independent stacks like `GitHubRunnerStack` or the AI Engagement stacks.

⚠️ **NEVER delete AWS resources (stacks, buckets, tables, etc.) without explicit approval from The Brougham 22.** Even ROLLBACK_COMPLETE stacks — always ask first.

### Phase 5.5: Validate AgentCore Runtime (if Python AI engagement changed)

1. Check Runtime env vars are intact (deploy wipes them):
   ```bash
   aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id <ID> --query 'environmentVariables'
   ```
   Must contain: `ATHENA_WORKGROUP`, `ATHENA_DATABASE`, `ASG_NAME`, `BEDROCK_AGENTCORE_MEMORY_ID`.
   If missing, re-set via `update_agent_runtime` (see `Docs/Production/agentcore-runtime-deployment.md`).
2. Check SSM feature flag: `aws ssm get-parameter --name "/extralife/ai-engagement/use-agentcore-runtime"`
3. Check ECR for `:cache` tag (only if `build-and-push-runtime` ran with caching enabled):
   ```bash
   aws ecr describe-images --repository-name extralife-ai-engagement-runtime \
     --query 'imageDetails[?imageTags[?contains(@,`cache`)]].imageTags' --output text
   ```
   **Absence of `:cache` tag on the first run is expected** — buildx silently skips a missing cache source and builds from scratch. The tag is created on first run and reused on subsequent runs. Only flag as an issue if the tag is absent on the second+ run.
4. Test invoke: `agentcore invoke '{"message":"hello","sessionId":"test","actorId":"test","context":{"eventId":1,"teamId":1}}'`
4. Check OTEL spans: `aws logs filter-log-events --log-group-name "aws/spans" --filter-pattern "el_ai_engagement" --limit 3`
   - If no spans: check Runtime logs for "Attempting to instrument while already instrumented" — means Powertools Tracer is conflicting with `opentelemetry-instrument`. Verify `POWERTOOLS_TRACE_DISABLED` fix is in deployed image.
5. Check eval config `serviceNames` matches `{agent_name}.DEFAULT`
6. Send 2-3 test messages through admin chat UI, wait 15-20 min, then check eval results:
   ```bash
   aws logs filter-log-events \
     --log-group-name "/aws/bedrock-agentcore/evaluations/results/extralife_ai_chat_eval-91hBCjAdv4" \
     --region us-west-2 --limit 5
   ```
   Verify results have `score` + `label` fields — **not** `error.type: LogEventMissingException`.
   If still `LogEventMissingException`: check that eval config `dataSourceConfig` includes BOTH `aws/spans` AND the Runtime log group (`/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT`).

### Phase 6: End-to-End Smoke Test

1. If Lambda changed: invoke with a realistic test payload that exercises the changed code path. Verify response content, not just 200 status.
2. If Lambda uses Web Adapter: verify the `/health` endpoint responds. Check CloudWatch logs for `Runtime.ExitError` — this indicates the startup script (`run.sh`) failed (e.g., module not on PATH, missing deps).
3. If ECS changed: craft a Lambda invocation that mimics the ECS→Lambda flow (include context payload with test data).
3. Check CloudWatch logs for the test invocations — verify no errors, correct tool routing, expected data flow.

### Phase 7: Report

Present a deployment validation summary:

**Also include a trace quality sample** if Lambda or ECS changed:
1. Pull 5 recent `ChatQuery` traces from CloudWatch (post-deploy timestamp).
2. For each trace, present: query, response_time_ms, tools_invoked, any warnings.
3. Ask The Brougham 22 for a quick binary Pass/Fail on each.
4. If any fail, flag as a quality regression and recommend running `eval-chat-traces` for deeper analysis.

```
| Component | Status | Evidence |
|-----------|--------|----------|
| Lambda    | ✅     | LastModified: <timestamp>, package verified |
| ECS       | ✅     | Image pushed: <timestamp>, 2/2 tasks running |
| SQL Procs | ✅     | Archived at <timestamp>, proc returns data |
| CDK       | N/A    | No infrastructure changes |
```

Flag any discrepancies (e.g., "ECS image is stale — last pushed 3 days ago").

## Key Resource Lookups

These resource names are project-specific. Check CDK stack outputs or session handoff for current values:
- Lambda function names: `extralife-ai-engagement-agent`, `extralife-ops-advisor`
- ECS cluster/service: found via `aws ecs list-clusters` / `aws ecs list-services`
- ECR repository: `extralife-web-admin`
- S3 stored procedures bucket: found via `aws s3 ls | grep storedprocedure`
- CloudWatch log groups: `/aws/lambda/<function-name>`, ECS log group from CDK

## Rules

- Always verify timestamps — "is the deployed code newer than the CI/CD run?"
- Don't assume deployment succeeded just because CI/CD passed — verify the artifact landed.
- For Lambda, download and inspect the actual package — don't trust config alone.
- For ECS, check both the image push time AND the service deployment time.
- When SQL procs changed, chain to `run-sql-validation` for logic verification.
- Report discrepancies clearly — stale deployments are a common source of "it works locally but not in dev" bugs.
- When moving a spec to Done after validation, do it on the current feature branch — never commit directly to develop.
- **Agent tool wiring check**: If the change added a new agent with tools that call AWS APIs (ASG, CloudWatch, S3, etc.), verify the Lambda has: (1) the required env vars (e.g., `ASG_NAME`), (2) the IAM permissions for those API calls. Tools deployed without env vars/IAM fail silently at runtime.
- **Private API check**: If the change calls external APIs (GitHub, etc.) from Angular, verify the repo/resource is publicly accessible. Private repos return 404/422 from unauthenticated browser calls.
- Refer to the user as "The Brougham 22".

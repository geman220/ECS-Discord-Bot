---
name: model-eval
description: Run a side-by-side model evaluation for an agent, comparing two Bedrock models on identical queries.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Model Eval

Run a side-by-side model evaluation for an agent, comparing two Bedrock models on identical queries.

## When to Run

- Before switching an agent's model (e.g., Nova Lite → Sonnet)
- After prompt changes that might affect model-specific behavior
- When evaluating a new model release for an existing agent
- Periodically to verify model quality hasn't regressed

## Input

- Agent name (e.g., "keeper", "captain", "scout")
- Model A ID (current model, e.g., `us.amazon.nova-2-lite-v1:0`)
- Model B ID (candidate model, e.g., `us.anthropic.claude-sonnet-4-6`)
- Optional: custom eval queries (defaults to Athena traces, then generated)

## Process

### Phase 0: Build Dataset from Athena Traces (optional)

If no custom queries provided, pull real user queries from Athena to build a domain-specific eval dataset:

1. Query Athena for recent chat traces: `SELECT message, tools_invoked, response_time_ms FROM extralife_chat_logs.chat_logs WHERE agent = '{agent_name}' ORDER BY timestamp DESC LIMIT 50`
2. Filter to high-quality traces: has tool invocation, response_time < P90, no errors
3. Deduplicate similar queries (fuzzy match on message text)
4. Select 10 diverse queries covering: happy path, tool usage, edge cases
5. For each query, record the "ground truth": which tool should be called, what the correct answer looks like
6. Save as JSONL to `eval-datasets/{agent_name}-{date}.jsonl` for reuse

If Athena has insufficient traces (< 20 for the agent), fall back to generating queries in Phase 1.

### Phase 1: Define Eval Queries

1. If dataset from Phase 0, use those queries.
2. If custom queries provided, use those.
3. Otherwise, generate 10 queries:
   - 3 happy-path queries (basic functionality)
   - 3 tool-usage queries (verify correct tool invocation)
   - 2 edge-case queries (ambiguous input, missing data)
   - 1 guardrail query (should be refused)
   - 1 multi-step query (requires chaining tools or reasoning)
4. Document the queries with expected behavior for each.

### Phase 2: Run Model A (Current)

1. Verify current model ID: `aws lambda get-function-configuration`
2. Run all queries through the Lambda with unique session IDs (`eval-{model}-q{N}`)
3. Collect: response text, response time, tools invoked (from CloudWatch ChatQuery logs)
4. Record any errors or failures

### Phase 3: Swap and Run Model B (Candidate)

1. Swap the model env var: `aws lambda update-function-configuration --environment`
2. Wait 3 seconds for Lambda to update
3. Run the same queries with different session IDs (`eval-{modelB}-q{N}`)
4. Collect same metrics as Phase 2
5. **⚠️ IMMEDIATELY restore Model A** after all queries complete. Verify restoration.

### Phase 4: Score with LLM-as-Judge

See [Scoring Template](references/SCORING-TEMPLATE.md) for the judge prompt and comparison table format.


### Phase 5: Summarize and Recommend

Present:
- Scoring summary table (criteria × model, PASS/FAIL counts)
- Key findings (e.g., "Model B hallucinates dates", "Model A struggles with multi-step")
- Cost comparison (per-query cost for each model)
- Latency comparison (P50, P90)
- **Recommendation**: keep current, switch, or hybrid

### Phase 6: Document

Add a `## Model Evaluation` section to the relevant spec with:
- Date, models compared, query count, dataset source (Athena traces vs manual)
- Full results table with judge verdicts
- Key findings
- Decision and rationale

Optionally export the eval dataset + results to S3 in Bedrock Model Evaluation JSONL format for future use with Bedrock's built-in eval tools.

## Rules

- Always restore the original model after evaluation. Verify with `get-function-configuration`.
- Use unique session IDs per query per model to avoid context bleed.
- Run queries sequentially (not parallel) to avoid Lambda concurrency issues.
- Prefer Athena traces over generated queries — real user behavior is the best eval dataset.
- The judge model should be different from both models being evaluated (avoid self-grading).
- If a model fails >50% of queries, stop early and report.
- Log the model swap and restoration in telemetry.
- Refer to the user as "The Brougham 22".

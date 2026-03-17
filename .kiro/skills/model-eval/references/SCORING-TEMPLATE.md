# LLM-as-Judge Scoring Template

### Phase 4: Score with LLM-as-Judge

Use Bedrock LLM-as-Judge for automated, repeatable scoring. For each query + response pair:

1. Build a judge prompt:
   ```
   You are evaluating an AI agent's response. Score each criterion as PASS or FAIL with a one-line explanation.

   Query: {query}
   Expected tool: {expected_tool}
   Expected behavior: {expected_behavior}
   Actual response: {response}
   Tools invoked: {tools}

   Criteria:
   1. Correct tool usage — did it invoke the expected tool?
   2. Factual accuracy — are dates, numbers, names correct?
   3. Response completeness — did it answer the full question?
   4. Guardrail compliance — did it refuse off-topic requests?
   ```
2. Send to a judge model (use Sonnet — strongest available for judgment)
3. Parse PASS/FAIL for each criterion
4. Also record: response time in ms

**Fallback**: If LLM-as-Judge is unavailable, fall back to manual binary scoring.

Present as a comparison table:

```
| # | Query | Model A | Model B | Judge Verdict |
|---|-------|---------|---------|---------------|
| Q1 | "Any errors today?" | PASS (3/3), 13s | PASS (2/3) wrong date, 20s | Model A |
```

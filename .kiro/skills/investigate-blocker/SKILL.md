---
name: investigate-blocker
description: Systematic investigation of a technical blocker using tools to verify assumptions, document evidence, and create escalation artifacts for external teams.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Investigate Blocker

Systematic investigation of a technical blocker using tools to verify assumptions, document evidence, and create escalation artifacts for external teams.

## When to Run

When a feature is blocked by an external dependency (AWS service limitation, SDK capability gap, third-party API issue) and you need to:
1. Verify the blocker is real (not a configuration issue)
2. Document evidence for escalation
3. Create artifacts for external teams (GitHub issue, support ticket, team doc)

## Input

- Description of the blocker
- What you've tried so far
- Which external team(s) to escalate to

## Output

1. Investigation findings logged to the spec
2. GitHub issue documenting the blocker
3. Markdown file for external team(s) with technical details

## Workflow

**⚠️ TELEMETRY: Log `{"type":"skill","skill":"investigate-blocker","status":"started"}` BEFORE doing anything else.**

### Phase 1: Verify the Blocker

Use tools to confirm the blocker is real, not a configuration or implementation issue.

**For SDK/Framework limitations**:
1. Download and inspect the deployed package (Lambda zip, container image)
2. Check source code for the missing capability
3. Search package contents for related classes/methods
4. Verify with SDK documentation

**For AWS service limitations**:
1. Read AWS documentation with `aws___read_documentation`
2. Check API reference for alternative approaches
3. Verify deployed configuration matches requirements
4. Check service status for known issues

**For configuration issues**:
1. Compare deployed config vs documented requirements
2. Check IAM permissions
3. Verify resource policies
4. Check CloudWatch logs for errors

**Document each verification** with:
- Tool used
- Command/query executed
- Output/evidence
- Conclusion (confirmed blocker vs configuration issue)

### Phase 2: Document Evidence

Create a findings section in the spec with:

```markdown
### Blocker Investigation (YYYY-MM-DD HH:MM)

**Verified with Tools**:

1. **[Component] source code** (tool: execute_bash, grep, fs_read):
   - Evidence: [what you found]
   - Conclusion: [capability exists/missing]

2. **[Service] documentation** (tool: aws___read_documentation):
   - Evidence: [quote from docs]
   - Conclusion: [requirement confirmed]

3. **Deployed configuration** (tool: aws CLI):
   - Evidence: [config output]
   - Conclusion: [matches/doesn't match requirements]

**Conclusion**: [Blocker confirmed / Configuration issue / Alternative exists]
```

### Phase 3: Create Escalation Artifacts

**GitHub Issue**:
1. Use project's issue template if it exists
2. Include:
   - Problem statement (what's blocked)
   - Current state (what's working, what's missing)
   - Technical details (verified with tools)
   - Questions for external team(s)
   - Impact (what we lose without this)
   - Workaround options
3. Add appropriate labels
4. Link to spec and related PRs

**External Team Document** (markdown file in `Docs/`):
1. Executive summary (1-2 paragraphs)
2. Technical details with evidence
3. What we've tried (iteration history)
4. Specific questions for each team
5. Sample data (spans, configs, logs)
6. Impact and next steps

### Phase 4: Present Summary

Present to The Brougham 22:
- Blocker confirmed with [N] tool verifications
- GitHub issue #XXX created
- External team doc: `Docs/{filename}.md`
- Recommended next steps:
  1. Share doc with [team names]
  2. Wait for response or implement workaround
  3. Track in issue #XXX

## Rules

- Every claim must be verified with a tool — no assumptions
- Document the tool used and output for each verification
- If a verification contradicts your hypothesis, update the hypothesis
- Max 10 verification attempts before concluding (prevents infinite loops)
- Always create both GitHub issue AND external team doc
- Refer to the user as "The Brougham 22"

## Example Verifications

**SDK capability**:
```bash
# Download package
aws lambda get-function --function-name X --query 'Code.Location' | xargs curl -o pkg.zip
# Check for class/method
unzip -p pkg.zip path/to/file.py | grep "def method_name"
```

**AWS service requirement**:
```
aws___read_documentation(url="https://docs.aws.amazon.com/service/...")
# Look for "required", "must", "cannot"
```

**Deployed config**:
```bash
aws service get-config --id X --query 'field' --output json
# Compare to documented requirements
```

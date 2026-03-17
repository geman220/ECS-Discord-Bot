---
name: research-service
description: Evaluate an AWS service or feature for adoption. Produces a structured recommendation with region availability, architecture mapping, and a file-or-skip decision.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Research Service

Evaluate an AWS service or feature for adoption. Produces a structured recommendation with region availability, architecture mapping, and a file-or-skip decision.

## When to Run

When The Brougham 22 asks "should we use X?" or "evaluate X for our system" for any AWS service, feature, or third-party tool.

## Process

### Step 1: Research

Use `web_search`, `aws___search_documentation`, `aws___read_documentation`, and `web_fetch` to gather:
- What the service does (one paragraph)
- Key capabilities and features
- Pricing model
- SDK/framework compatibility

**For non-AWS dependencies** (SDKs, frameworks, libraries):
- Use tools to verify claimed capabilities (don't trust docs alone)
- Check source code or package contents for the specific methods/classes needed
- Example: If evaluating "Strands SDK for OTEL logs", check if `StrandsTelemetry` has `setup_logs_exporter()`
- Document verification: "Verified in source: [file/class/method exists/missing]"

### Step 1.5: Verify SDK/Framework Capabilities

**⚠️ MANDATORY for any service that requires SDK integration. Skip this step = mid-implementation architecture pivots.**

**If the service requires SDK or framework support**:

1. **Check SDK availability in BOTH languages** (Python + .NET for our stack):
   ```python
   # Python: Check boto3 client methods
   import boto3
   client = boto3.client('service-name', region_name='us-west-2')
   print([m for m in dir(client) if 'invoke' in m.lower() or 'relevant_method' in m.lower()])
   print('Signing name:', client.meta.service_model.signing_name)  # IAM service prefix
   ```
   ```bash
   # .NET: Check NuGet package exists and has the method
   dotnet add package AWSSDK.ServiceName
   grep -r "MethodName" ~/.nuget/packages/awssdk.servicename/*/lib/netstandard2.0/*.xml
   ```

2. **Verify IAM service prefix** — the signing_name from boto3 IS the IAM prefix. Don't guess:
   ```python
   client.meta.service_model.signing_name  # e.g., "bedrock-agentcore" not "bedrock-agent"
   ```

3. **Check package contents** (for deployed code):
   ```bash
   # If deployed, download and inspect
   aws lambda get-function --function-name X | jq -r '.Code.Location' | xargs curl -o pkg.zip
   unzip -l pkg.zip | grep "package_name"
   unzip -p pkg.zip path/to/file.py | grep "class ClassName\|def method_name"
   ```

4. **Check documentation** vs **actual source**:
   - Docs may claim a feature exists
   - Source code is ground truth
   - If mismatch, flag as "docs outdated" or "feature not implemented"

5. **Document findings**:
   ```markdown
   **SDK Verification**:
   - Package: strands-agents v1.29.0
   - Claimed capability: OTEL logs export
   - Verified in source: ❌ `StrandsTelemetry` has no `setup_logs_exporter()` method
   - boto3 client: ✅ `invoke_agent_runtime` exists
   - .NET SDK: ✅ `AWSSDK.BedrockAgentCore` v4.0.11.1 has `InvokeAgentRuntimeAsync`
   - IAM prefix: `bedrock-agentcore` (verified via signing_name)
   - Conclusion: SDK support confirmed, feature gap in framework only
   ```

**Why this matters**: The #419 blocker was caused by assuming Strands SDK exported OTEL events (it doesn't — Runtime does). Six iterations of OTEL fixes before discovering the real issue. SDK verification with tools would have caught this in Phase 0 research.

### Step 2: Region Check

Verify the service is available in **us-west-2** (our region). Check the service's supported regions page. If not in us-west-2, flag as a blocker.

### Step 3: Map to Our System

Create a table mapping the service's capabilities to our current architecture:

| Our Current Approach | Service Replacement | Improvement |
|---------------------|-------------------|-------------|

Identify what it replaces, what it complements, and what it doesn't address.

### Step 4: Recommend

One of three verdicts:
- **✅ Adopt now** — clear value, available in our region, reasonable effort
- **⏳ Not yet** — good service but wrong timing (missing prereqs, architecture mismatch, preview-only)
- **🔴 Skip** — doesn't solve our problems or adds more complexity than value

Include:
- Why this verdict
- What would change the verdict (for "not yet")
- Suggested phased approach (if adopting)
- Effort estimate (trivial / small / medium / large)

### Step 5: Present

Structured output:
```
## {Service Name} — Should We Adopt It?

### What It Is
{One paragraph}

### Region: us-west-2 {✅/❌}

### How It Maps to Our System
{Table}

### Recommendation: {Adopt now / Not yet / Skip}
{Rationale}

### Suggested Approach (if adopting)
Phase 1: ...
Phase 2: ...
```

### Step 6: File (if adopting)

If the recommendation is "Adopt now", offer to file a GitHub issue using our issue template with the research findings included.

## Rules

- Always check us-west-2 availability — don't assume.
- Always map to our specific system, not generic benefits.
- Be honest about effort — don't undersell architecture changes.
- Include cost estimate when possible.
- Reference related open issues that the service might address.
- Refer to the user as "The Brougham 22".

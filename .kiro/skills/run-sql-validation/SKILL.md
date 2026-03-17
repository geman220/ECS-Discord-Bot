---
name: run-sql-validation
description: Generate and present SQL validation queries for a new or modified stored procedure. The user runs the queries against RDS and reports results back.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Run SQL Validation

Generate and present SQL validation queries for a new or modified stored procedure. The user runs the queries against RDS and reports results back.

## Input

A stored procedure name or file path (e.g., "GetTopDonors" or "Database/StoredProcedure_GetTopDonors.sql").

## Process

### Phase 1: Read the Proc

1. Find and read the stored procedure file from `Database/`.
2. Identify: parameters, JOINs, WHERE filters, GROUP BY, ORDER BY, aggregations.

### Phase 2: Generate Validation Queries

Generate numbered queries in order of diagnostic value:

1. **Basic execution** — call the proc with no optional filters (all defaults). Confirms it runs and returns data.
2. **Filtered execution** — call with each optional parameter individually. Confirms filters work.
3. **Data existence** — `SELECT COUNT(*)` on the primary tables to confirm data is present.
4. **JOIN integrity** — `SELECT TOP 5` with the proc's JOIN to confirm relationships exist.
5. **Filter aggressiveness** — count rows before and after WHERE filters to confirm filters aren't excluding too much data.
6. **Edge cases** — queries for known edge cases:
   - NULL/empty values in filtered columns
   - Boundary values for numeric parameters
   - Cross-year data if the proc spans events

Present all queries to the user as a numbered list with explanations.

### Phase 3: Collect and Analyze Results

As the user reports results:
- Confirm expected vs actual for each query
- Flag discrepancies (e.g., "proc returns $48K but raw SUM is $52K — $4K gap from excluded rows")
- Identify root causes for gaps
- Determine if gaps are acceptable or need fixes

### Phase 4: Report

Present a validation summary:
```
| Query | Result | Status | Notes |
|-------|--------|--------|-------|
| #1 Basic exec | 10 rows returned | ✅ | Top donor $2,257 |
| #2 Participant filter | 10 rows for Keith Hodo | ✅ | Matches expected |
| #3 Data exists | 1,514 donations / 73 participants | ✅ | Sufficient data |
| #4 JOIN works | Donations linked to participants | ✅ | |
| #5 Filter check | 1,505/1,514 pass (9 excluded) | ✅ | Reasonable |
```

## Rules

- Always start with the simplest query (just execute the proc) before diagnostic queries.
- Explain what each query is checking and why — the user is running these manually.
- Use the proc's actual table/column names, not generic placeholders.
- Compare aggregated results against raw `SELECT SUM/COUNT` to catch exclusion gaps.
- If a gap is found, identify exactly which filter causes it and whether it's intentional.
- This skill is often chained from `validate-deployment` Phase 4 when SQL changes are detected.
- Refer to the user as "The Brougham 22".

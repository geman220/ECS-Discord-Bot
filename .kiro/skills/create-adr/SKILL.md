---
name: create-adr
description: Create an Architectural Decision Record (ADR) to document a design choice or technical strategy.
metadata:
  author: ssfcultra
  version: "1.0"
---
# Create ADR

Create an Architectural Decision Record (ADR) to document a design choice or technical strategy.

## Input

A description of the technical decision, or a reference to a recent decision made in the conversation.

## Process

### Phase 1: Gather Context
1. Identify the core technical decision and its rationale.
2. Review the conversation history or ask the user for specific details:
   - **Context**: What was the problem or requirement?
   - **Decision**: What did we choose to do?
   - **Alternative**: What other options were considered and why were they rejected?
   - **Consequences**: What are the pros, cons, and maintenance impacts of this choice?

### Phase 2: Draft ADR
1. Use the standard ADR template:
   ```markdown
   # ADR: {YYYYMMDDii} - {Short Description}

   ## Status
   Accepted

   ## Context
   {The background and problem...}

   ## Decision
   {The technical choice made...}

   ## Consequences
   - **Pros**: ...
   - **Cons**: ...
   - **Maintenance**: ...
   ```
2. Generate the ID using the current date and user initials (default: `kh`). Format: `YYYYMMDDii`.

### Phase 3: Save and Commit
1. Define the filename: `{ID}-{kebab-case-description}.md`.
2. Ensure the `/docs/adr/` directory exists.
3. Save the file to `/docs/adr/{filename}`.
4. Stage and commit the new ADR with a message: `docs: record ADR {ID} - {description}`.

## Output

A new Architectural Decision Record file in `/docs/adr/` committed to the repository.

## Rules

- Always use the `YYYYMMDDii` format for IDs.
- Ensure consequences are balanced (Pros and Cons).
- Link to related ADRs if they exist.
- Refer to the user as "The Brougham 22".

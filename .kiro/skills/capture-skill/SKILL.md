---
name: capture-skill
description: Create a new Kiro CLI skill (prompt) from a conversation, a pasted prompt, or a description.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Create Skill

Create a new Kiro CLI skill (prompt) from a conversation, a pasted prompt, or a description.

## Input

Optional: a name for the new skill (e.g., "refactor-code"). Will ask if not provided.

## Process

### Step 1: Gather Source Material

Ask the user to provide one of:
1. **A prompt they've written** — paste the text directly
2. **A description of what the skill should do** — help draft it
3. **Reference to earlier in this conversation** — extract the relevant workflow

### Step 2: Analyze and Structure

From the provided material, identify:
- **Core purpose** — what does this skill accomplish?
- **Required inputs** — what arguments does it need?
- **Step-by-step process** — break into clear phases
- **Expected outputs** — what files/artifacts are produced?
- **Error cases** — what could go wrong?

### Step 3: Draft the Skill

Create a markdown prompt following the structure of existing skills in `.kiro/prompts/`:

```markdown
# {Skill Name}

{One-line description}

## Input

{Describe expected input or arguments}

## Process

### Phase 1: {Name}
{Steps...}

### Phase 2: {Name}
{Steps...}

## Output

{What the user gets when complete}

## Rules

- {Constraints and conventions}
- Refer to the user as "The Brougham 22".
```

### Step 4: Review with User

Present the draft and ask:
- Does this capture what you wanted?
- Any steps to add or remove?
- Confirm the skill name.

### Step 5: Save

1. Validate name: alphanumeric, hyphens, underscores only. Max 50 characters.
2. Save to `.kiro/prompts/{name}.md`
3. Confirm creation and show how to use it: `/prompts` → select `{name}`

## Skill Naming Rules

- ✅ Valid: `review-pr`, `debug-test`, `deploy-stacks`
- ❌ Invalid: `my skill` (spaces), `review.code` (dots)

## Rules

- Keep skills focused — one skill per workflow.
- Include verification steps where appropriate.
- Make the skill self-contained — readable cold.
- Ask the user rather than guessing on unclear points.
- Refer to the user as "The Brougham 22".

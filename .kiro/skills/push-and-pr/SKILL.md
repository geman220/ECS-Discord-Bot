---
name: push-and-pr
description: Commit (if needed), push the current branch to origin, and generate a pull request description in the chat.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Push and PR

Commit (if needed), push the current branch to origin, and generate a pull request description in the chat.

## Process

1. **Pre-Push Validation**:
   - Check if the current branch is cleanly ahead of `origin/master` (or the primary base branch). If it contains unrelated commits from other features, warn the user and offer to rebase onto a fresh branch from `origin/master`.
   - Verify write permissions by running `git push --dry-run origin <branch>`.
   - If `403 Permission Denied` occurs:
     - Check for a configured `fork` remote (`git remote -v`).
     - If a fork exists, offer to push to `fork` and create a cross-repository PR.
     - If no fork exists, explain that direct push failed and provide instructions for creating a fork.
2. Check `git status` — if there are uncommitted changes, ask the user if they want to commit first.
3. Push to the verified remote (either `origin` or `fork`).
4. Read the PR template from `.github/PULL_REQUEST_TEMPLATE.md`.
4. Read `git log develop..HEAD --oneline` and `git diff develop --stat` to understand the scope of changes.
5. Fill out the PR template with:
   - Description summarizing the branch's purpose
   - Correct change type checkboxes
   - Related issue number
   - Detailed changes list (grouped by area: Python, .NET, CDK, etc.)
   - Testing status with current test counts
   - Security considerations
   - Deployment notes (deploy order, new resources, migration steps)
6. Display the filled-out PR description as markdown directly in the chat — do NOT create a file.
7. Show the GitHub PR creation link: `https://github.com/khodo-lab/extralife/pull/new/<branch>`

## Rules

- Never push to `main` or `develop` directly.
- If the current branch IS `main` or `develop`, STOP and ask the user to create a feature branch first. Do not proceed.
- Always read the actual PR template — don't guess the format.
- The PR description is displayed in chat only — not saved as a file.
- Include deploy order when CDK changes are involved (Tier 2 Platform before Tier 3 Compute).
- For lightweight PRs (single-concern bugfixes, infra changes), a shorter PR body is acceptable — cover description, type of change, related issue, changes made, and deployment notes. Skip sections that don't apply (screenshots, security checklist for non-security changes).
- **Default to `gh pr create`** to create the PR directly on GitHub. **CRITICAL:** Do not pass the markdown body directly via the `--body` argument, as complex strings cause bash escaping failures. You MUST write the generated PR description to a temporary file (e.g., `.github/PR_BODY.md`), run `gh pr create --body-file .github/PR_BODY.md ...`, and then delete the temporary file. Only fall back to displaying the PR description in chat if `gh` CLI is not installed or the user explicitly asks for a preview.
- **Before `gh pr create`**: Run `gh auth status` to verify the token has PR creation scope. If it returns 403 or "Resource not accessible", tell the user: "gh auth needs re-login — run `gh auth login` in your terminal, then I'll retry." Do NOT attempt to use the runner PAT from SSM for PR creation — it lacks the required scope.
- Refer to the user as "The Brougham 22".

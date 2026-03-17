# Branching Workflow

## Critical Rules

**NEVER commit directly to `main` or `develop` branches.**

## Required Workflow

1. **Start from develop**: Always create feature branches from `develop`
   ```bash
   git checkout develop
   git pull origin develop
   git checkout -b feature/your-feature-name
   ```

2. **Work in feature branch**: Make all changes in your feature branch

3. **Merge to develop first**: Create PR from feature branch → `develop`

4. **Then merge to main**: Create PR from `develop` → `main` for production releases

## Before Making Changes

If the user is about to make code changes, remind them:
- "Should we create a feature branch for this work?"
- Suggest a branch name based on the work: `feature/description` or `bugfix/description`

## When Changes Are Complete

After completing work in a feature branch:
1. Commit and push the feature branch
2. Remind user to create PR to `develop` via GitHub UI
3. After develop deployment is verified, remind about creating PR to `main`

## Branch Naming

- Features: `feature/add-prize-drawing`
- Bug fixes: `bugfix/fix-winner-display`
- Infrastructure: `infra/update-cdk-stack`
- Hotfixes: `hotfix/critical-security-patch` (from main, merge to both main and develop)

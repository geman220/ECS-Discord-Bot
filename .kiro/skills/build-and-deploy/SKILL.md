---
name: build-and-deploy
description: Build a container image for linux/amd64 (Fargate), push to ECR, and rotate the ECS Fargate service.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Build and Deploy

Build a container image for linux/amd64 (Fargate), push to ECR, and rotate the ECS Fargate service.

## When to Run

When the user wants to see UI changes live without waiting for CI/CD. This is a manual deploy — CI/CD will overwrite it on the next merge to develop.

## Prerequisites

- Podman machine running (`podman machine start`)
- AWS credentials valid (`aws sts get-caller-identity`)
- ECR login (`aws ecr get-login-password | podman login`)

## Process

### Step 1: Clean and Build

```bash
podman system prune -af  # Avoid OOM — reclaim disk space
podman build --platform linux/amd64 \
  --build-arg CERT_PASSWORD="localdev321" \
  -t 851725441346.dkr.ecr.us-west-2.amazonaws.com/extralife-web-admin:latest \
  -f Source/ExtraLife.Web.Admin/Dockerfile .
```

⚠️ Must use `--platform linux/amd64` — Mac ARM builds won't run on Fargate x86.

### Step 2: Push to ECR

```bash
aws ecr get-login-password --region us-west-2 | podman login --username AWS --password-stdin 851725441346.dkr.ecr.us-west-2.amazonaws.com
podman push 851725441346.dkr.ecr.us-west-2.amazonaws.com/extralife-web-admin:latest
```

### Step 3: Rotate Fargate

```bash
CLUSTER=$(aws ecs list-clusters --region us-west-2 --query "clusterArns[?contains(@, 'ExtraLife')]" --output text | head -1)
SERVICE=$(aws ecs list-services --cluster "$CLUSTER" --region us-west-2 --query "serviceArns[?contains(@, 'Admin')]" --output text | head -1)
aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --force-new-deployment --region us-west-2
```

### Step 4: Verify

Wait 2-3 minutes, then confirm:
- `aws ecs describe-services` shows 2/2 running tasks with new task definition
- The UI change is visible in the browser

## Rules

- This only deploys the ECS container (Angular + .NET). It does NOT deploy CDK changes, Lambda code, or stored procedures.
- For CDK changes, use CI/CD (`git push` → GitHub Actions → `cdk deploy`).
- For Lambda changes, use CI/CD (`git push` → GitHub Actions → Lambda deploy).
- If podman machine is not running, start it first.
- If podman runs out of memory, increase with `podman machine set --memory 6144`.
- Refer to the user as "The Brougham 22".

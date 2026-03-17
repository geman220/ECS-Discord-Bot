# Security Policy

## Supported Versions

We release patches for security vulnerabilities for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |
| develop | :white_check_mark: |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to: [keith@thehodos.com]

You should receive a response within 48 hours. If for some reason you do not, please follow up via email to ensure we received your original message.

Please include the following information:

- Type of issue (e.g., SQL injection, sensitive data exposure, cross-site scripting, etc.)
- Full paths of source file(s) related to the manifestation of the issue
- The location of the affected source code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce the issue
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit it

## Security Best Practices

### For Contributors

1. **Never commit secrets** - Use GitHub Secrets for sensitive data.
2. **Protect `.env` files** - Ensure `.env` is never committed.
3. **Keep dependencies updated** - Regularly update `pip` requirements.
4. **Review security alerts** - Check Dependabot alerts for both Python and Node.js.
5. **Role Hierarchy** - Ensure the Discord bot's role is never over-privileged and its hierarchy is properly managed.
6. **Use branch protection** - All changes must go through pull requests.

### For Deployments

1. **Use OIDC authentication** - No long-lived AWS credentials in GitHub.
2. **Least privilege IAM roles** - Deployment roles have minimal required permissions.
3. **Environment protection** - Production deployments require approval.
4. **Database Security** - Ensure Postgres is only accessible within the VPC or via secure tunnels.

## Security Features Enabled

- ✅ Dependabot security updates
- ✅ Code scanning with CodeQL
- ✅ Secret scanning
- ✅ Branch protection rules
- ✅ Required pull request reviews
- ✅ OIDC for AWS authentication

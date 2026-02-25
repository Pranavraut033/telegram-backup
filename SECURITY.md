# Security Policy

## Supported versions

Security fixes are provided on the `main` branch and current release tags.

## Reporting a vulnerability

Please do not open public issues for suspected vulnerabilities.

1. Open a private GitHub security advisory for this repository.
2. Include impact, reproduction steps, and suggested remediation if available.
3. Allow maintainers time to investigate and prepare a fix before disclosure.

## Scope

- Secret leakage in code/workflows/docs
- Authentication/session handling weaknesses
- Unsafe file handling that can cause data loss or exfiltration

## Best practices for users

- Store credentials only in `.env` and never commit it.
- Rotate Telegram API credentials if they are exposed.
- Keep backups in access-controlled storage.

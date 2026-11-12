# Security policy

## Supported versions

Until the first stable release, security fixes are applied to the current default development branch. A release support policy will be published with `1.0.0`.

## Reporting a vulnerability

Do not publish exploit details in a public issue. Use GitHub's private vulnerability reporting for this repository, or contact the maintainers through a private channel listed on the GitHub profile. Include affected commit/tag, impact, reproduction steps, and any practical mitigations. Do not include real customer data or secrets.

## Security expectations

- Keep secrets outside source control and rotate exposed credentials immediately.
- Treat model output, uploaded files, connector responses, and external documents as untrusted input.
- Enforce identity, workspace scope, and authorization on the server for every request.
- Use least-privilege integration credentials and separate sandbox from production accounts.
- Require approval for financial, customer-impacting, publishing, or irreversible actions.
- Pin and scan dependencies; review transitive licenses and advisories.
- Exercise backup restoration and incident response before production deployment.

## Current limitations

The repository is currently a documentation and governance bootstrap, not a production application. Do not connect live commerce accounts or use it to process customer or payment data.

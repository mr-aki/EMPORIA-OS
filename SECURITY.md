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

## Current scope and limitations

Emporia currently contains an executable FastAPI backend foundation, including workspace-scoped identity and authorization, provider adapters, advisory agents and skills, network research, a PostgreSQL-backed background job queue, workspace usage/cost accounting, and a fail-closed business-action approval API.

It is not yet a complete commerce operating system or a production-ready deployment. Direct commerce-platform integrations and external business-action executors are not implemented. The API's live provider behavior depends on operator-managed credentials, provider access, quotas, and network configuration; CI tests use mocked upstream calls and do not prove live deployment readiness.

Before using a deployment with real commerce accounts or customer/payment data, complete a deployment-specific threat model and security review, verify secrets and network boundaries, exercise backup restoration and recovery, and establish monitoring, alerting, load/failure testing, and incident response. Do not treat a passing CI run as a substitute for those release gates.

<div align="center">

# Emporia OS

**The open operating system for building and running commerce businesses.**

AI-agnostic · Open source · Self-hostable · Human-governed

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-7C5CFC?style=for-the-badge&logo=apache)](LICENSE)
![Stage: executable backend foundation](https://img.shields.io/badge/Stage-Executable%20Backend%20Foundation-0F766E?style=for-the-badge)

</div>

---

> **Honest status:** Emporia now has an executable FastAPI backend with venture records, workspace-scoped access, audit events, a multi-provider AI gateway, advisory specialist agents, and an optional web-research connector. It is an early backend foundation, not yet a complete commerce operating system or a production-ready service. There is no finished dashboard, no live commerce-platform connector, and no autonomous business-action runtime.

## Product direction

Commerce teams work across research, products, suppliers, storefronts, customers, campaigns, fulfilment, finance, and disconnected tools. Emporia OS aims to bring these operations into one coherent workspace while allowing each operator to choose AI providers and retain control over consequential actions.

The long-term platform combines:

- **Venture studio** — research opportunities, test assumptions, compare business models, and manage launch gates.
- **Product and market intelligence** — evaluate products, competitors, sellers, specifications, and demand signals.
- **Sourcing and procurement** — assess suppliers, RFQs, samples, MOQs, quality, and landed cost.
- **Store operations** — coordinate catalogues, listings, inventory, orders, fulfilment, and customer support.
- **Revenue and growth** — manage customer journeys, campaigns, retention, and measured experiments.
- **Portfolio and finance** — manage multiple brands and business units with separated records and consolidated visibility.
- **Governed AI workforce** — delegate bounded work to specialists with explicit tools, budgets, evaluations, and approvals.

These are product goals, not claims that every module exists today.

## Implemented backend slices

| Capability | Current implementation |
|---|---|
| API and persistence | FastAPI service, SQLAlchemy records, venture CRUD, health checks, SQLite local mode, PostgreSQL deployment path |
| Identity and workspaces | Password-based registration/login, JWT access tokens, workspace memberships, role-based write checks, workspace isolation |
| Audit trail | Persistent audit events for venture, AI, agent, research, and workspace lifecycle operations |
| AI provider gateway | Server-side adapters for OpenAI, Anthropic, Gemini, and operator-configured OpenAI-compatible endpoints |
| Specialist agents | Eight versioned advisory agents with category/deliverable metadata, persisted runs, usage, status, and history |
| Commerce skills | 15 versioned advisory procedures with typed inputs, validation, token ceilings, workspace-scoped run history, and audit events |
| Web research | Explicit Brave Search LLM Context API connector with source metadata and untrusted-context handling |
| Database lifecycle | Alembic migrations, Docker Compose startup migration, migration coverage for fresh and legacy schemas |

See [API setup and endpoint documentation](apps/api/README.md) and the [verified project status](docs/engineering/PROJECT_STATUS.md).

## Engineering principles

1. **Evidence before confidence.** A specification, prompt, mock, or UI control is not a working capability.
2. **Small real slices over giant catalogues.** Build and verify connected functionality before multiplying components.
3. **Provider independence without pretending APIs are identical.** Preserve provider-specific capabilities and limitations.
4. **Human authority over consequential actions.** Autonomy must be bounded, visible, auditable, and revocable.
5. **Security from the beginning.** Enforce identity, workspace isolation, least privilege, secret hygiene, and approval policies at execution boundaries.
6. **No production-ready label without proof.** Reliability, security, backup/restore, and deployment gates must pass.

## Explicit limits

- Agent and skill runs are advisory text generation. Models cannot execute shell commands, browse arbitrary sites, change a storefront, issue refunds, move money, or perform other business actions.
- Live model and Brave requests require the operator's own server-side API credentials and provider entitlements. Automated tests mock upstream HTTP calls.
- Workspace invitations, email verification, MFA, password reset, refresh-token rotation, and a full identity-provider integration are not implemented.
- The frontend dashboard, commerce connectors, async job queue, approval engine, permissioned tool runtime, and business-domain modules remain future implementation work.
- No production-readiness or security-certification claim is made.

## Development lifecycle

Capabilities advance through this lifecycle:

specified → implemented → integrated → evaluated → security_reviewed → production_ready

A component advances only when the corresponding source, tests, integration evidence, and operational controls exist. See [PROJECT_STATUS.md](docs/engineering/PROJECT_STATUS.md).

## Contributing

Read [AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md) before proposing changes. Prefer focused pull requests with tests, security considerations, and honest status updates.

## License

Emporia OS is distributed under the [Apache License 2.0](LICENSE). Third-party services, models, integrations, dependencies, and contributed assets remain subject to their own terms and licenses.

<div align="center">

**Build with evidence. Delegate with boundaries. Operate with confidence.**

</div>

<div align="center">

# Emporia OS

**The open operating system for building and running commerce businesses.**

AI-agnostic · Open source · Self-hostable · Human-governed

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-7C5CFC?style=for-the-badge&logo=apache)](LICENSE)
![Stage: backend foundation](https://img.shields.io/badge/Stage-Backend%20Foundation-0F766E?style=for-the-badge)

</div>

---

> **Honest status:** Emporia now contains a runnable FastAPI backend foundation, authenticated workspace-scoped venture APIs, an audit trail, a multi-provider text-generation gateway, a source-linked Brave Search adapter, and an eight-specialist advisory agent runtime with persisted run history. These are working backend slices, not a finished commerce platform. There is not yet a dashboard, live store-admin action layer, approval workflow, job queue, or production deployment. Live AI and research calls require operator-supplied server-side API credentials.

## The vision

Commerce teams work across research, products, suppliers, storefronts, customers, campaigns, fulfilment, finance, and disconnected tools. Emporia OS aims to bring these operations into one coherent workspace while allowing each operator to choose their AI providers and retain control over consequential actions.

The intended platform combines:

- **Venture studio** — research opportunities, test assumptions, compare business models, and manage launch gates.
- **Product and market intelligence** — evaluate products, competitors, sellers, specifications, and demand signals.
- **Sourcing and procurement** — assess suppliers, RFQs, samples, MOQs, quality, and landed cost.
- **Store operations** — coordinate catalogues, listings, inventory, orders, fulfilment, and customer support.
- **Revenue and growth** — manage customer journeys, campaigns, retention, and measured experiments.
- **Portfolio and finance** — manage multiple brands and business units with separated records and consolidated visibility.
- **Governed AI workforce** — delegate bounded work to specialists with explicit tools, budgets, evaluations, and approvals.

These are product goals, not claims of current implementation.

## Current repository contents

The repository now includes project governance, an executable API foundation, agent definitions and runtime, provider adapters, network research, tests, and CI. Governance files remain the working standards:

| File | Purpose |
|---|---|
| [AGENTS.md](AGENTS.md) | Repository-wide instructions for human and AI contributors |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution workflow and quality expectations |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Community participation standards |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting and security expectations |
| [SUPPORT.md](SUPPORT.md) | Support guidance |
| [CHANGELOG.md](CHANGELOG.md) | Record of committed project changes |
| [Project status](docs/engineering/PROJECT_STATUS.md) | Capability lifecycle and verified implementation status |

## Engineering principles

1. **Evidence before confidence.** A specification, prompt, mock, or UI control is not a working capability.
2. **Small real slices over giant catalogues.** Build and verify connected functionality before multiplying components.
3. **Provider independence without pretending APIs are identical.** Preserve provider-specific capabilities and limitations.
4. **Human authority over consequential actions.** Autonomy must be bounded, visible, auditable, and revocable.
5. **Security from the beginning.** Enforce identity, workspace isolation, least privilege, secret hygiene, and approval policies at execution boundaries.
6. **No production-ready label without proof.** Reliability, security, backup/restore, and deployment gates must pass.

## Current executable backend

The API includes server-side adapters for OpenAI, Anthropic, Gemini, and operator-configured OpenAI-compatible model endpoints. It includes eight advisory commerce specialists with authenticated execution, persisted run history, token usage, and audit events. An optional Brave Search connector supplies source-linked research context only when the caller explicitly submits a separate research query. Provider API keys are server-side secrets; consumer chat subscriptions do not provide API credentials.

These agents cannot currently browse the operator's stores, change prices or listings, send campaigns, issue refunds, or perform other external business actions. Approval gates, role-based multi-user identity, job queues, tool sandboxes, and live commerce connectors remain future milestones.

## Development status

Capabilities follow this lifecycle:

`specified → implemented → integrated → evaluated → security_reviewed → production_ready`

See [the project status document](docs/engineering/PROJECT_STATUS.md). A capability advances only when its evidence exists.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before proposing changes. Prefer focused pull requests with tests, security considerations, and honest status updates.

## License

Emporia OS is distributed under the [Apache License 2.0](LICENSE). Third-party services, models, integrations, dependencies, and contributed assets remain subject to their own terms and licenses.

<div align="center">

**Build with evidence. Delegate with boundaries. Operate with confidence.**

</div>

# Project status

**Product:** Emporia OS  
**Repository:** mr-aki/EMPORIA-OS  
**License:** Apache-2.0  
**Release stage:** Executable backend foundation — not production-ready

Emporia OS is an open-source, self-hostable, AI-provider-independent operating system for planning and operating commerce businesses. The current implementation is a real backend foundation; the broader commerce workspace and user experience are still being built.

## Status semantics

| State | Meaning |
|---|---|
| specified | Requirements and contracts exist; no implementation is claimed. |
| implemented | Source code exists and relevant automated tests cover its behavior. |
| integrated | The component is connected to its real dependencies and exercised end-to-end. |
| evaluated | Quality, behavior, and failure cases have measurable evaluation evidence. |
| security_reviewed | Threats, permissions, data handling, and relevant security tests have been reviewed. |
| production_ready | Operational, security, reliability, backup/restore, and release gates have passed for a stated deployment profile. |

A document, prompt, registry entry, mock, or UI control is not proof that a capability is implemented. Passing unit tests alone does not prove production readiness.

## Implemented backend capabilities

| Capability | State | Evidence and limits |
|---|---|---|
| API foundation | implemented | FastAPI app, health endpoints, venture CRUD, request validation, SQLAlchemy persistence |
| Identity | implemented | Password hashing, JWT access tokens, account registration/login, active-user checks |
| Workspace isolation | implemented | Server-derived workspace identity, membership re-check on authenticated requests, owner/admin/operator write roles, viewer read-only behavior |
| Database migrations | implemented | Alembic migration for fresh databases and compatibility with the earlier venture/audit/agent-run schema; tests cover fresh and legacy database upgrades |
| Audit events | implemented | Persistent event records for venture changes, AI calls, agent runs, research calls, and workspace creation |
| AI provider gateway | implemented | OpenAI, Anthropic, Gemini, and operator-configured OpenAI-compatible adapters; upstream HTTP contracts are tested with mocks |
| Specialist agent runtime | implemented | Eight versioned advisory definitions, public category/deliverable metadata, persisted run history, token usage, and terminal failure handling for unexpected research/provider exceptions |
| Network research | implemented | Explicit Brave Search connector, bounded regional search requests, source metadata, response validation, rate-limit mapping, and untrusted external-context handling |
| FX reference rates | implemented | Keyless Frankfurter daily rate client with latest/historical lookup, in-process caching, Decimal conversion, request validation, and workspace audit events |
| Commerce skills | implemented | 45 versioned advisory skills across three implementation packs, typed input contracts, bounded validation, provider-backed execution, workspace-scoped persisted runs, token ceiling, and audit events |

The latest API pull request must pass GitHub Actions before its changes are considered verified on the default branch. Local and CI provider tests do not prove that a deployment has working credentials, quotas, DNS, or live provider access.

## Security and operational boundaries

- Account registration is disabled by default. Operators must explicitly enable it for controlled provisioning.
- JWTs are checked against the current active user and current workspace membership on each authenticated request; removing membership invalidates an existing token for that workspace.
- Clients cannot select a tenant by sending an arbitrary workspace header or request-body field.
- Passwords are hashed; API keys remain server-side secrets and are not returned by provider catalogue responses.
- The legacy static bearer token is accepted only in development mode. Production deployments must use JWT authentication and a strong JWT signing secret.
- The current identity layer does not yet provide email verification, MFA, password reset, refresh-token rotation, login throttling, or workspace invitations.
- Agent models have no action tools. Commerce actions, permission grants, approval records, budgets, sandboxing, and revocation enforcement must be implemented before enabling external actions.
- Live external API behavior depends on operator-supplied credentials and the terms, rate limits, and quotas of each provider.

## Not implemented

- Production frontend/dashboard and responsive operator workspace.
- Direct Shopify, WooCommerce, Amazon, marketplace, payment, logistics, accounting, and CRM integrations.
- Complete product, catalogue, supplier, purchase-order, inventory, fulfilment, customer-support, marketing, and finance domains.
- Background task queue, workflow scheduler, multi-agent coordination, agent evaluation service, and durable retry/dead-letter handling.
- Permissioned action-tool registry, human approval flows, spend controls, and execution sandbox.
- Team invitations and full identity lifecycle features.
- Production hardening evidence: threat model, independent security review, rate limiting, backup/restore drills, monitoring/alerting, load tests, disaster recovery, and a deployment-specific release gate.

## Engineering principle

Prefer a small end-to-end capability that is real, testable, observable, and safe over a large catalogue of unconnected specifications. Expand capability only with explicit contracts, ownership, tests, evaluation cases, and operational boundaries.

## Skills implementation slice

The Skills runtime contains a versioned 60-skill commerce catalog across four reviewed
implementation packs. Every skill has a typed input contract, required/unknown-field
validation, bounded payloads, an ordered procedure, output sections, and explicit
guardrails. Authenticated executions are persisted and scoped to the current workspace,
with start/completion/failure audit events. All skills remain advisory; they do not grant
store, payment, supplier, advertising, fulfilment, or customer-action permissions.

Pack v1 covers opportunity, product, sourcing, marketplace, growth, pricing, and retention.
Selected skills produce deterministic Decimal-based landed-cost/margin, inventory-reorder,
and promotion calculations. Pack v2 adds customer persona/JTBD, brand/portfolio planning,
bundling, SEO and review mining, quality inspection, supplier continuity, stock aging,
fulfilment economics, and promotional calendars. Pack v3 adds pricing-response and discount
planning, lifecycle segmentation and subscription retention, customer-support taxonomy,
launch/market-entry readiness, supplied-policy/claims evidence review, paid-media work,
content calendars, and localization.

Pack v4 adds contribution-margin waterfalls, P&L variance, cash conversion, CAC and LTV,
paid-media pacing and creative fatigue, catalogue/attribute quality, variant architecture,
image and copy QA, warehouse slotting, order-exception analysis, and fulfilment capacity.
Contribution waterfall, CAC, and cohort contribution LTV are computed server-side with
Decimal arithmetic and returned as verified calculation payloads for the AI to explain.

Numeric array item bounds are published in the API contract and validated before provider
calls. Policy/claims skills analyze supplied materials; they do not verify live policies or
provide legal approval. CI, evaluations, and security review remain release gates.

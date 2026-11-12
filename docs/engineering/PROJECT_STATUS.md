# Project status

**Product:** Emporia OS  
**Repository:** `mr-aki/EMPORIA-OS`  
**License:** Apache-2.0  
**Release stage:** Executable backend foundation (early development; not production-ready)

Emporia OS is an open-source, self-hostable, AI-provider-independent operating system for planning and operating commerce businesses. The current repository contains a working backend foundation and advisory agent runtime. The broader commerce operating system remains under active development.

## Status semantics

| State | Meaning |
|---|---|
| `specified` | Requirements and contracts exist; no implementation is claimed. |
| `implemented` | Source code exists and relevant unit tests pass. |
| `integrated` | The component is connected to its real dependencies and exercised end-to-end. |
| `evaluated` | Quality, behavior, and failure cases have measurable evaluation evidence. |
| `security_reviewed` | Threats, permissions, data handling, and relevant security tests have been reviewed. |
| `production_ready` | Operational, security, reliability, backup/restore, and release gates have passed for a stated deployment profile. |

A document, prompt, registry entry, mock, or UI control is not proof that a capability is implemented. Passing unit tests with mocked upstream services is not proof of live-provider reliability or production readiness.

## Verified implementation

| Capability | Current state | Evidence and boundary |
|---|---|---|
| FastAPI service and health endpoints | `implemented` | Liveness and database readiness endpoints; CI test suite. |
| Venture CRUD and workspace scoping | `implemented` | Authenticated CRUD with workspace ID controlled by server configuration. |
| Application audit trail | `implemented` | Database-backed audit events for current API mutations and agent execution. |
| AI provider gateway | `implemented` | OpenAI, Anthropic, Gemini, and operator-configured OpenAI-compatible adapters; HTTP adapter tests use mocked transports. |
| Advisory specialist runtime | `implemented` | Eight versioned specialist definitions, authenticated run endpoint, persisted status/output/token usage, and audit events. |
| Explicit network research | `implemented` | Brave Search LLM Context API adapter; callers must provide a separate research query. Live use requires a server-side Brave API key. |
| Automated API checks | `implemented` | GitHub Actions workflow runs Ruff and pytest on Python 3.12. |

## Current specialist workforce

All eight specialists use the same provider-backed execution and run-history pipeline:

1. `commerce-strategist` — business model, positioning, validation, and launch gates.
2. `product-research-analyst` — product opportunities, customer problems, competition, and evidence quality.
3. `growth-marketing-planner` — acquisition, funnel, creative experiments, and measurement.
4. `pricing-unit-economics-analyst` — price architecture, cost stack, contribution margin, and break-even.
5. `supplier-sourcing-analyst` — sourcing briefs, RFQs, supplier checks, quality planning, and landed cost.
6. `customer-voice-analyst` — review and feedback themes, journey friction, and evidence-linked insights.
7. `marketplace-listing-optimizer` — listing copy, product attributes, marketplace SEO, and claim checks.
8. `retention-lifecycle-specialist` — activation, post-purchase, repeat purchase, loyalty, and win-back journeys.

The API exposes public metadata (category, expertise, expected deliverables, and required context) but does not expose private system prompts. The agents are advisory: no browser, shell, store-admin, payment, CRM-send, or other consequential action tools are granted.

## Not yet implemented

- Dashboard and operator-facing workspace UI.
- Multi-user authentication, workspace membership, and role-based access control.
- Durable background queue, worker processes, cancellation, and stale-run recovery.
- Per-agent and per-workspace cost budgets, rate limits, quotas, and idempotency controls.
- Scoped tool grants, sandboxed execution, approval records, and human-in-the-loop action gates.
- Live commerce platform connectors and verified read/write workflows.
- Database migration and backup/restore automation.
- Production observability, deployment hardening, and recovery procedures.
- Agent quality evaluation datasets and repeatable model/provider evaluation runs.

## Next engineering sequence

1. Harden agent execution: budgets, quotas, idempotency, cancellation, and crash-safe run lifecycle.
2. Add policy-governed read-only tools and evidence capture before any write-capable tools.
3. Add explicit approval records and scoped write actions for low-risk commerce operations.
4. Build the operator dashboard and connect it to the authenticated API.
5. Add production identity, migrations, observability, backup/restore, and deployment gates.

## Engineering principle

Prefer a small end-to-end capability that is real, testable, observable, and safe over a large catalogue of unconnected specifications. Every capability must advance through the lifecycle only when its evidence exists.
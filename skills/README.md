# Emporia OS Skills

Skills are versioned, reusable commerce procedures. They define bounded analysis; they do
not grant access to external systems or authorize business actions.

## Core commerce pack v1

The API ships 15 executable advisory procedures:

| Skill ID | Domain | Purpose |
|---|---|---|
| market-opportunity-scan | strategy | Screen a niche using evidence, customer pain, competition, and feasibility |
| competitor-teardown | intelligence | Compare competitors from supplied observations |
| customer-problem-synthesis | customer | Synthesize interview, review, and support notes |
| product-validation-plan | venture | Design low-cost tests for risky assumptions |
| product-page-audit | merchandising | Diagnose product-page clarity and conversion friction |
| listing-copy-brief | catalog | Draft fact-grounded channel listing copy |
| supplier-scorecard | sourcing | Compare supplier candidates with a transparent scorecard |
| supplier-rfq-builder | sourcing | Draft a supplier-ready request for quotation |
| landed-cost-margin-analysis | finance | Model per-unit landed cost and contribution economics |
| inventory-reorder-review | operations | Calculate reorder signals from demand and lead time |
| pricing-promotion-review | pricing | Evaluate price and discount contribution economics |
| campaign-brief-development | marketing | Build a measurable campaign plan |
| funnel-conversion-diagnostic | growth | Diagnose drop-offs from supplied funnel data |
| retention-experiment-plan | lifecycle | Design retention experiments with customer safeguards |
| returns-reason-diagnostic | customer-operations | Prioritize product and fulfilment fixes from return patterns |

Definitions and input validation live in
apps/api/src/emporia_api/skills/registry.py. The API uses those definitions for catalog
metadata, input checks, and execution prompts.

## API

All endpoints require the workspace bearer token.

- GET /api/v1/skills — list the catalog.
- GET /api/v1/skills?domain=sourcing — filter by domain.
- GET /api/v1/skills/{skill_id} — inspect one skill's input/output contract.
- POST /api/v1/skills/{skill_id}/runs — execute with a configured model provider.
- GET /api/v1/skill-runs — list recent runs in the configured workspace.
- GET /api/v1/skill-runs/{run_id} — retrieve a run and its result.

Each skill declares input keys and value types. Unknown keys, missing required fields,
wrong types, oversized text, and oversized payloads are rejected before an upstream call.

## Execution and governance

- A run records skill ID/version, provider/model, input data, output, status, token usage,
  provider request ID, and timestamps.
- Start, completion, and failure are audit events. Raw input values are not copied into
  audit details.
- Runs and history are scoped to the server-configured workspace.
- The runner uses the server-side provider gateway; browser clients never send provider keys.
- Skill inputs are untrusted data and cannot override the system procedure.
- Skills do not browse URLs, send RFQs, update listings, place purchase orders, change
  prices, launch campaigns, or modify customer records. Such actions need separate
  capability grants and policy checks.
- CI uses a fake provider gateway and does not consume external API credits.

## Lifecycle

This pack is implemented as an authenticated advisory runtime with validation, persistence,
workspace scoping, and audit events. It has not yet been independently evaluated or
security-reviewed for production deployment. Do not label it production_ready.

The catalogue is intentionally a useful first pack rather than 135 placeholder prompts.
Expand by domain with real input contracts, failure cases, evaluations, and security review.

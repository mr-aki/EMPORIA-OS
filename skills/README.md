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


## Deterministic calculation engine

Three skills return server-calculated numeric results in the "calculations"
field of each run and pass the same values to the language model as authoritative context:

- landed-cost-margin-analysis: freight/unit, duty/unit, landed cost/unit,
  channel fees, contribution, contribution margin, and break-even price.
- inventory-reorder-review: lead-time demand, reorder point, inventory position,
  days of cover, reorder gap, and MOQ-aware suggested order quantity.
- pricing-promotion-review: current and promotional contribution, target-margin
  price floor, and the unit-volume uplift needed to preserve contribution.

Calculations use decimal arithmetic and publish four-decimal precision. Monetary
currency is supplied by the operator; no exchange-rate conversion is performed.
For customs duty, duty_base_per_unit can be supplied explicitly. When omitted,
the calculator uses supplier unit cost as a provisional base and marks that assumption
in the result; confirm the applicable customs valuation basis before making a decision.

Reorder inputs treat inbound units as confirmed and usable. The suggested quantity
is a review aid based on the reorder gap and MOQ, not a purchase order. Pricing outputs
exclude advertising, refunds, fixed costs, and taxes unless already included in the
supplied landed cost. These are operating calculations, not tax, customs, or accounting advice.


## Core commerce pack v2 (skills 16–30)

| Skill ID | Domain | Purpose |
|---|---|---|
| customer-persona-builder | customer | Build evidence-labelled buying personas from anonymized research and purchase evidence |
| jobs-to-be-done-map | customer | Map customer progress, triggers, alternatives, and switching barriers |
| brand-positioning-framework | strategy | Develop substantiated positioning and a testable message hierarchy |
| product-portfolio-prioritizer | merchandising | Prioritize products by strategic fit, economics, demand evidence, and complexity |
| assortment-gap-analysis | merchandising | Identify customer-need, feature, and price-tier coverage gaps |
| product-bundle-architect | merchandising | Design coherent complementary bundles and evaluate margin/fulfilment trade-offs |
| keyword-cluster-planner | seo | Build intent-led keyword clusters and map them to pages |
| marketplace-search-term-audit | seo | Audit supplied marketplace query exports for relevance, waste, and coverage |
| review-theme-miner | intelligence | Extract strengths, defects, unmet expectations, and improvement themes from reviews |
| quality-inspection-plan | quality | Create risk-based inspection checkpoints, acceptance rules, and escalation paths |
| supplier-continuity-risk-assessment | sourcing | Assess supply interruption exposure and mitigation options |
| supplier-quote-comparison | sourcing | Normalize supplier quotations and compare total commercial exposure |
| stock-aging-obsolescence-review | operations | Review stock age, expiry exposure, excess cover, and disposition options |
| fulfilment-unit-economics | operations | Compare pick/pack, storage, shipping, returns, and minimum charges |
| promotional-calendar-planner | marketing | Coordinate promotions around verified events, inventory, margin, and channel readiness |

Pack v2 follows the same governed execution path as pack v1: every skill has a version,
typed input contract, objective, ordered procedure, required output sections, and
skill-specific guardrails. The runtime rejects unknown input keys and validates required
fields before provider calls. All pack v2 skills remain advisory; no provider, marketplace,
supplier, inventory, pricing, or campaign action is performed by executing a skill.


## Core commerce pack v3 (skills 31–45)

| Skill ID | Domain | Purpose |
|---|---|---|
| pricing-elasticity-scenario-planner | pricing | Design price-response tests and compare evidence-backed price scenarios |
| discount-ladder-review | pricing | Review discount tiers, margin floors, and stacking risks |
| lifecycle-segmentation-planner | lifecycle | Design permission-aware lifecycle segments and suppression rules |
| subscription-retention-diagnostic | lifecycle | Diagnose recurring-order churn and customer-respecting retention options |
| support-contact-taxonomy | customer-operations | Build consistent support issue categories and routing |
| customer-complaint-root-cause | customer-operations | Turn complaint evidence into corrective and preventive actions |
| product-launch-readiness | venture | Assess cross-functional launch blockers and go/no-go gates |
| product-market-entry-brief | strategy | Plan staged market entry with operating and diligence requirements |
| marketplace-policy-readiness | compliance | Map supplied marketplace policy material to product/listing evidence |
| claims-substantiation-audit | compliance | Check marketing claims against supplied evidence and limitations |
| paid-media-creative-brief | advertising | Build evidence-led paid media creative concepts and test plans |
| campaign-structure-audit | advertising | Audit supplied ad campaign exports, naming, audience overlap, and tracking |
| lifecycle-email-flow-planner | lifecycle | Plan consent-aware triggered email journeys |
| commerce-content-calendar | content | Coordinate customer-led commerce content by channel and date |
| ecommerce-localization-brief | international | Plan locale-specific product, content, and commerce adaptations |

The third pack is still advisory. In particular, policy and claims skills analyze operator-supplied
documents and evidence; they do not fetch current regulations, verify live marketplace rules,
certify a product, or provide legal approval.


## Core commerce pack v4 (skills 46–60)

| Skill ID | Domain | Purpose |
|---|---|---|
| contribution-margin-waterfall | finance | Reconcile revenue into contribution before and after acquisition spend |
| profit-loss-variance-diagnostic | finance | Explain P&L movements and operational variance drivers |
| cash-conversion-cycle-review | finance | Assess inventory, receivable, payable days, and cash-cycle levers |
| customer-acquisition-cost-review | growth | Calculate media-only and fully loaded CAC using supplied allocation rules |
| cohort-ltv-estimator | growth | Estimate steady-state contribution LTV with explicit churn assumptions |
| paid-media-budget-pacing-review | advertising | Compare planned and actual campaign spend and pacing |
| creative-fatigue-diagnostic | advertising | Separate creative fatigue from audience, offer, auction, and tracking changes |
| product-catalogue-data-quality-audit | catalog | Find missing, duplicate, conflicting, and malformed catalogue data |
| product-attribute-normalizer | catalog | Normalize attributes with source traceability and explicit conversion rules |
| product-variant-architecture | catalog | Design variant parent/child structures and valid option combinations |
| product-image-asset-brief | content | Specify accurate product imagery, asset coverage, and visual QA |
| product-description-fact-check | catalog | Validate listing claims against approved product specifications |
| warehouse-slotting-review | operations | Assess SKU placement, velocity, space, and handling constraints |
| order-exception-diagnostic | operations | Diagnose order lifecycle failures, handoffs, and stuck states |
| fulfilment-capacity-planner | operations | Compare forecast workload against labour, station, and carrier capacity |

Pack v4 introduces deterministic contribution-margin waterfall, customer acquisition cost,
and cohort contribution LTV calculations. Their values are computed server-side with
Decimal arithmetic and returned in the run's \`calculations\` field; the model receives
the same values for explanation. CAC allocation, cohort definitions, and margin inputs
remain operator-supplied assumptions.

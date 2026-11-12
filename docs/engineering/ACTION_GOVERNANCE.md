# Governed business-action lifecycle

## Purpose

Agents and skills may recommend an action, but a recommendation is not permission to perform it. The API stores allow-listed action proposals, requires a second workspace authority for approval, and records every transition. This layer is a governance foundation, not a live commerce connector.

## State machine

~~~text
pending_approval ── approve by a different owner/admin ──> approved
       │
       ├── reject by a different owner/admin ───────────> rejected
       │
       └── cancel by requester/owner/admin ─────────────> cancelled

approved ── cancel before execution ─────────────────────> cancelled
approved ── execute request without adapter ────────────> approved (blocked + audited)
~~~

Terminal states (rejected, cancelled) cannot be re-approved. The requester cannot approve or reject their own request. A separate owner/admin must decide. The current implementation deliberately does not have an executed state because no external adapter is registered.

## Allow-list and contract validation

The current catalogue defines proposals for:
- catalog.product.update
- inventory.stock.adjust
- marketing.campaign.publish
- orders.refund.issue

Each type has an explicit field contract and risk label. Unknown action types and unknown input fields are rejected. Input values must be JSON-safe; payloads are limited to 16 KB and 32 top-level fields. Secret-like property names are rejected. Idempotency keys are unique within a workspace and cannot be reused for a different request.

## Authorization

- Owners, admins, and operators can create requests.
- Owners and admins can approve or reject requests.
- Requesters cannot decide their own requests; they can cancel them.
- A requester or workspace owner/admin can cancel pending or approved requests.
- Only the workspace owner can add existing registered accounts to the workspace and grant a role. Admins cannot grant new roles.
- Every route derives tenant scope from the verified principal. Client-supplied workspace IDs are not accepted as authorization context.

## Execution boundary

All action definitions currently report executor_available=false. The execute endpoint:
1. requires owner/admin authority,
2. requires the request to be approved,
3. records and audits the missing-adapter reason, and
4. returns HTTP 409 without changing request status or making an external call.

Before any connector is enabled, it must provide explicit permission scopes, idempotency, precondition checks, budget/spend controls where relevant, dry-run or preview semantics, result verification, observability, rate limits, and a rollback/compensation plan appropriate to its domain. High-risk actions require a documented approval policy. External execution must remain unavailable by default.

## Operational follow-up

This release does not yet implement email invitations, spend limits, connector sandboxing, live executors, scheduled approval expiry, or distributed execution workers. It is not evidence that live store/payment mutations are available or production-ready.

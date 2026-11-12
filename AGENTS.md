# Repository-wide agent instructions

## Product intent
Build Emporia OS as a coherent, self-hostable commerce operating system. Treat this file as engineering guidance, not as authorization to access external systems.

## Non-negotiable rules
- Never represent a specification, prompt, mock, fixture, or UI element as a working capability.
- Use explicit lifecycle states: specified, implemented, integrated, evaluated, security_reviewed, production_ready.
- Never commit API keys, access tokens, customer exports, payment data, or real `.env` files.
- Skills describe reusable procedures; they do not grant permissions.
- Every external action must be declared as a capability and evaluated by policy immediately before execution.
- Read/write operations must be workspace-scoped. Never trust a workspace ID supplied by an untrusted request body or header.
- High-impact commerce actions require an approval record from a different authorized principal.
- External calls need timeouts, bounded retries, idempotency where applicable, and structured error handling.
- Add tests for success, failure, authorization, tenant boundaries, and policy behavior.
- Prefer accessible, responsive, calm UI over decorative complexity.

## Working method
1. Read the relevant domain docs and existing implementation before editing.
2. State the smallest meaningful vertical slice and its acceptance criteria.
3. Implement contracts and behavior together.
4. Run relevant tests, linting, type checks, and repository validation.
5. Update implementation status and docs to match evidence.
6. Summarize changed files, checks run, outcomes, and known limits.

## Architecture boundaries
- `apps/` contains deployable applications.
- `packages/` contains reusable code with stable public interfaces.
- `agents/`, `skills/`, and `workflows/` are versioned product definitions, not executable permission grants.
- `contracts/` contains language-neutral schemas.
- `infra/` contains reproducible local and deployment infrastructure.

# Contributing to Emporia OS

Thank you for helping build a commerce platform that is useful, inspectable, and safe to operate.

## Before opening a change

1. Read `AGENTS.md` and the current implementation-status document.
2. Confirm whether the capability is specified, implemented, integrated, evaluated, security-reviewed, or production-ready.
3. Prefer one reviewable vertical slice over broad, unrelated edits.

## Pull request expectations

- Explain the user or operator problem being solved.
- Link the relevant issue or product requirement when one exists.
- Include tests for behavior and failure modes.
- Include authorization and workspace-isolation tests for data access changes.
- Include migration and rollback notes for database changes.
- Document provider-specific behavior, rate limits, and credentials where relevant.
- Update capability lifecycle status honestly.
- Include screenshots for material UI changes and accessibility notes.

## Commit style

Use clear conventional messages such as `feat(api): add workspace-scoped venture search` or `docs(governance): clarify approval expiry`.

## Licensing

By submitting a contribution, you agree that it is offered under the repository's Apache-2.0 license unless a separate written agreement states otherwise. Do not submit code, graphics, datasets, or documentation unless you have the right to contribute them.

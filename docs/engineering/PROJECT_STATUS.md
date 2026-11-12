# Project status

**Product:** Emporia OS  
**Repository:** `mr-aki/EMPORIA-OS`  
**License:** Apache-2.0  
**Release stage:** Repository foundation

Emporia OS is an open-source, self-hostable, AI-provider-independent operating system for planning and operating commerce businesses. The intended scope includes venture discovery, market intelligence, sourcing, storefront operations, revenue, finance, portfolio management, and a governed AI workforce.

## Status semantics

| State | Meaning |
|---|---|
| `specified` | Requirements and contracts exist; no implementation is claimed. |
| `implemented` | Source code exists and relevant unit tests pass. |
| `integrated` | The component is connected to its real dependencies and exercised end-to-end. |
| `evaluated` | Quality, behavior, and failure cases have measurable evaluation evidence. |
| `security_reviewed` | Threats, permissions, data handling, and relevant security tests have been reviewed. |
| `production_ready` | Operational, security, reliability, backup/restore, and release gates have passed for a stated deployment profile. |

A document, prompt, registry entry, mock, or UI control is not proof that a capability is implemented. A passing unit test alone is not proof of production readiness.

## Verified repository state at bootstrap

The repository initially contained only the GitHub-generated README, Node-oriented ignore rules, and Apache-2.0 license. This commit adds governance and project documentation; it does not add a running application.

## Engineering principle

Prefer a small end-to-end capability that is real, testable, observable, and safe over a large catalogue of unconnected specifications. Expand capability only with explicit contracts, ownership, tests, evaluation cases, and operational boundaries.

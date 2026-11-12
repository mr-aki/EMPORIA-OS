# Emporia OS API

The current executable backend provides authenticated venture CRUD, workspace isolation, audit events, server-side AI provider adapters, advisory specialist agents, and optional Brave-backed web research.

## Requirements

- Python 3.12+
- PostgreSQL for shared deployments, or SQLite for local development
- Provider API credentials only for the external providers you intend to use

## Run locally with SQLite

From this directory:

~~~bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

export EMPORIA_ENVIRONMENT=development
export EMPORIA_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export EMPORIA_ALLOW_REGISTRATION=true

alembic upgrade head
uvicorn emporia_api.main:app --reload
~~~

OpenAPI documentation is available at http://localhost:8000/docs. Liveness and database readiness are available at /health/live and /health/ready.

### Create the first account

Registration is disabled by default. Enable it explicitly for controlled initial provisioning, then register an owner account:

~~~bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "owner@example.com",
    "password": "replace-with-a-long-unique-password",
    "display_name": "Workspace Owner",
    "workspace_name": "My Commerce Workspace"
  }'
~~~

The response includes a short-lived JWT access token. Keep it private:

~~~bash
export EMPORIA_ACCESS_TOKEN="paste-access-token-here"
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $EMPORIA_ACCESS_TOKEN"
~~~

After provisioning the required accounts, set EMPORIA_ALLOW_REGISTRATION=false and restart the API. The current identity layer does not yet include email verification, MFA, password reset, refresh tokens, login throttling, or workspace invitations. Do not expose unrestricted registration on a public deployment.

## Docker Compose

From the repository root:

~~~bash
cp .env.example .env
~~~

Before exposing the service, set EMPORIA_ENVIRONMENT=production, generate a strong EMPORIA_JWT_SECRET, choose unique PostgreSQL credentials, and set EMPORIA_DATABASE_URL to use the same database password as POSTGRES_PASSWORD. For example:

~~~text
EMPORIA_DATABASE_URL=postgresql+psycopg://emporia:YOUR_DB_PASSWORD@postgres:5432/emporia
POSTGRES_PASSWORD=YOUR_DB_PASSWORD
EMPORIA_JWT_SECRET=YOUR_LONG_RANDOM_SECRET
EMPORIA_ALLOW_REGISTRATION=false
~~~

For initial account provisioning, temporarily set EMPORIA_ALLOW_REGISTRATION=true, start the stack, create the required accounts, then set it back to false and restart the API.

~~~bash
docker compose up --build -d
docker compose logs -f api
~~~

The API container runs Alembic migrations before starting Uvicorn. PostgreSQL data is stored in the named emporia_postgres_data volume. Back up that volume and test restoration before relying on it.

The included Compose defaults are for local development only. Replace every example password and secret and configure TLS, network access controls, backups, monitoring, and a production deployment process before public exposure.

## Configuration

All settings use the EMPORIA_ prefix.

| Setting | Purpose |
|---|---|
| EMPORIA_DATABASE_URL | SQLAlchemy database URL; defaults to local SQLite |
| EMPORIA_ENVIRONMENT | Runtime environment; production disables legacy static-token authentication |
| EMPORIA_JWT_SECRET | JWT signing secret; production requires at least 32 characters |
| EMPORIA_JWT_ISSUER | JWT issuer claim; defaults to emporia-os |
| EMPORIA_JWT_ACCESS_TOKEN_MINUTES | Access-token lifetime; defaults to 60 minutes |
| EMPORIA_ALLOW_REGISTRATION | Explicit opt-in for account registration; defaults to false |
| EMPORIA_API_TOKEN | Development-only compatibility token for the original single-workspace setup |
| EMPORIA_WORKSPACE_ID | Legacy workspace identifier used while migrating an earlier deployment |
| EMPORIA_LEGACY_WORKSPACE_OWNER_EMAIL | Email allowed to claim legacy workspace data during first registration |
| EMPORIA_OPENAI_API_KEY | Optional server-side OpenAI API key |
| EMPORIA_ANTHROPIC_API_KEY | Optional server-side Anthropic API key |
| EMPORIA_GEMINI_API_KEY | Optional server-side Gemini API key |
| EMPORIA_OPENAI_COMPATIBLE_BASE_URL | Operator-configured OpenAI-compatible model endpoint |
| EMPORIA_OPENAI_COMPATIBLE_API_KEY | Optional server-side key for that endpoint |
| EMPORIA_BRAVE_SEARCH_API_KEY | Optional Brave Search LLM Context API key |
| EMPORIA_AGENT_MAX_OUTPUT_TOKENS | Server-side per-agent response ceiling; defaults to 2048 and must be 1–4096 |
| EMPORIA_SKILL_MAX_OUTPUT_TOKENS | Server-side per-skill response ceiling; defaults to 2048 and must be 1–4096 |

### Migrating an earlier single-workspace database

The migration adds identity/workspace tables and the research-source column while preserving existing venture, audit-event, and agent-run records. Before the first owner registration, retain the previous EMPORIA_WORKSPACE_ID and set EMPORIA_LEGACY_WORKSPACE_OWNER_EMAIL to the exact email address that will own the legacy data. The first registration with that email can claim the matching legacy workspace when legacy records exist and the workspace identifier is valid. Back up the database before applying migrations.

Run migrations manually for local/non-Docker deployments:

~~~bash
alembic upgrade head
~~~

## Authentication and workspace behavior

- POST /api/v1/auth/register creates an account and its first owner workspace when registration is enabled.
- POST /api/v1/auth/login verifies the password and issues a workspace-bound JWT.
- GET /api/v1/auth/me returns the authenticated account and its workspace memberships.
- POST /api/v1/auth/workspaces creates another workspace owned by the authenticated user.
- To switch workspace context, log in again with the desired workspace_id.
- Workspace identity is taken from the verified token and current membership, never from a client-selected header or request-body field.
- Owner, admin, and operator roles can perform write operations. Viewer membership is read-only.
- Membership is rechecked on each authenticated request, so removing a membership revokes access even before the JWT expires.

Passwords require at least 12 characters and are hashed with Argon2 through pwdlib. Access tokens expire; a refresh-token or token-rotation endpoint is not yet implemented.

## API endpoints

### System and commerce records

- GET /health/live
- GET /health/ready
- POST /api/v1/ventures
- GET /api/v1/ventures
- GET /api/v1/ventures/{id}
- PATCH /api/v1/ventures/{id}
- DELETE /api/v1/ventures/{id}
- GET /api/v1/audit-events

Venture and audit records are filtered to the workspace derived from the authenticated principal. Mutations append audit events in the same database transaction.

### AI provider gateway

The server-side gateway supports:

- OpenAI Chat Completions.
- Anthropic Messages.
- Google Gemini generateContent.
- Operator-configured OpenAI-compatible endpoints, including local model servers such as Ollama.

Endpoints:

- GET /api/v1/ai/providers returns configured providers and safe metadata, never credentials.
- POST /api/v1/ai/chat sends a bounded chat request to a configured provider.

Example:

~~~bash
curl -X POST http://localhost:8000/api/v1/ai/chat \
  -H "Authorization: Bearer $EMPORIA_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openai",
    "model": "gpt-5",
    "messages": [{"role": "user", "content": "Summarize my launch checklist."}],
    "max_tokens": 500
  }'
~~~

Provider keys stay on the server and are supplied through environment variables or a deployment secrets manager. Consumer chat subscriptions do not provide server-side API credentials. Live calls use the configured provider account's API billing, model access, quotas, and rate limits.

### Specialist agent runtime

Eight reviewed advisory definitions are registered and share the authenticated, persisted agent-run execution path:

- commerce-strategist — business model, positioning, validation strategy, and launch decisions.
- product-research-analyst — opportunity assessment, customer problems, evidence quality, and assortment risk.
- growth-marketing-planner — channel strategy, funnel design, and measurable acquisition experiments.
- pricing-unit-economics-analyst — price floors, contribution margin, break-even analysis, and scenario modelling.
- supplier-sourcing-analyst — sourcing briefs, RFQs, supplier due diligence, quality planning, and landed-cost inputs.
- customer-voice-analyst — customer feedback themes, evidence traceability, journey friction, and prioritised fixes.
- marketplace-listing-optimizer — product listings, marketplace SEO, merchandising briefs, and claim checks.
- retention-lifecycle-specialist — activation, post-purchase, repeat-purchase, loyalty, and win-back journeys.

Endpoints:

- GET /api/v1/agents lists public specialist metadata without exposing private system prompts.
- POST /api/v1/agents/{agent_id}/runs executes a specialist through one configured provider.
- GET /api/v1/agent-runs lists persisted runs for the current workspace.
- GET /api/v1/agent-runs/{run_id} retrieves one run.

The specialist metadata contract also includes category, expected deliverables, and required context; private system prompts are never returned. The server enforces EMPORIA_AGENT_MAX_OUTPUT_TOKENS (default 2048; allowed 1–4096) before creating a run or calling a provider. This is a per-run output bound, not a monthly budget or rate/concurrency limiter.

A run records its task, output, status, provider/model, token usage, request ID, timestamps, and selected research sources. Start, completion, and failure events are audited. Unexpected provider and research exceptions also finalize the persisted run as failed without exposing internal exception details to API clients.

**Safety boundary:** these agents are advisory text agents. They do not have browser, shell, store-admin, payment, or other action tools. They cannot autonomously change a live business.

### Network research connector

Emporia can retrieve source-linked web context through the official Brave Search LLM Context API. Configure EMPORIA_BRAVE_SEARCH_API_KEY on the API server to enable live research.

- POST /api/v1/research/search executes an authenticated, bounded search request.
- An agent run may set web_research=true and supply a separate research_query.

The separate query is explicit consent to send that query to Brave. The private task text, customer data, credentials, and supplier secrets are not forwarded automatically. Retrieved page content is untrusted evidence, not instructions. Agent history stores source URLs, titles, snippets, hostnames, and page-age metadata.

A valid Brave API key and active entitlement are required for live search. CI uses mocked HTTP responses and does not consume paid API requests.

## Quality checks

From this directory:

~~~bash
ruff check src tests
pytest -q
~~~

The test suite covers API contracts, authentication/authorization, workspace isolation, provider adapters, research privacy boundaries, and fresh/legacy database migrations. Provider HTTP tests use mocks; run a separately controlled integration test with operator credentials before relying on a live provider deployment.

## Skill catalog and execution

The core commerce catalog contains 30 versioned advisory procedures across two implementation packs. Skills are not
permission grants: the runtime does not browse supplied URLs, call store APIs, send supplier
messages, change prices, place orders, or launch campaigns.

Authenticated endpoints:
- GET /api/v1/skills — list metadata and input contracts.
- GET /api/v1/skills?domain=sourcing — filter by domain.
- GET /api/v1/skills/{skill_id} — inspect a skill contract.
- POST /api/v1/skills/{skill_id}/runs — execute through a configured AI provider.
- GET /api/v1/skill-runs and GET /api/v1/skill-runs/{run_id} — review run history.

Example request body:

    {
      "provider": "openai",
      "model": "gpt-5",
      "inputs": {
        "market": "Reusable home storage",
        "geography": "United Kingdom",
        "target_customer": "Renters in small urban apartments"
      },
      "max_tokens": 1800
    }

Each skill rejects unknown inputs and validates required fields and types before calling a
provider. The server enforces `EMPORIA_SKILL_MAX_OUTPUT_TOKENS` (default 2048, allowed range
1–4096) before persisting a run or calling the provider. Runs persist skill version, input data, result, provider usage, status, and
timestamps. Start/completion/failure events are written to the audit log; history is
workspace-scoped. Input values are untrusted data and cannot grant permissions or override
the skill procedure. See ../../skills/README.md for the catalog and governance boundaries.

### Search locale and rate limits

The research request accepts an explicit two-letter country code and search language:

```json
{
  "query": "ecommerce logistics and returns benchmarks",
  "country": "PK",
  "search_lang": "en",
  "maximum_number_of_tokens": 4096
}
```

`country` is passed to Brave as its two-letter search market; `search_lang` accepts a language tag such as `en` or `zh-hans`. Defaults remain `US` and `en`; select the target market that matches the research question rather than assuming the account's location is the target market.

The client spaces requests by at least one second per API process. Upstream HTTP 429 responses are surfaced as HTTP 429 with a bounded `Retry-After` value. This is a per-process guard; horizontally scaled deployments should use a shared rate limiter for a single API key. Review Brave's current [LLM Context documentation](https://api-dashboard.search.brave.com/documentation/services/llm-context) for the live contract, quotas and billing.

## Finance reference rates

Emporia includes a keyless connector to the official [Frankfurter v2 API](https://frankfurter.dev/). It exposes dated daily reference observations sourced from central banks and other official providers. No third-party API key is required.

Authenticated endpoints:

- `GET /api/v1/finance/fx/rate/{base}/{quote}?date=YYYY-MM-DD` — latest or historical pair observation.
- `POST /api/v1/finance/fx/convert` — multiply an amount by the selected pair's reference rate.

Example rate lookup:

```bash
curl -H "Authorization: Bearer $EMPORIA_ACCESS_TOKEN" \\
  http://localhost:8000/api/v1/finance/fx/rate/USD/PKR
```

Example conversion:

```bash
curl -X POST http://localhost:8000/api/v1/finance/fx/convert \\
  -H "Authorization: Bearer $EMPORIA_ACCESS_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "amount": "125.50",
    "base": "USD",
    "quote": "PKR"
  }'
```

Historical conversions can include a `date` field, for example `"date": "2025-12-31"`. Amounts and rates use decimal arithmetic. Latest observations are cached in-process for six hours; historical observations are cached for 24 hours. Responses preserve the actual observation date returned by the provider.

**Important limitation:** these are daily reference mid-market rates, not live bank, processor, card-network, remittance, or settlement quotes. They exclude FX spreads, fees, taxes, and provider-specific contractual pricing. Use actual settlement statements for accounting and reconciliation. The provider's documentation says blended rates are free for commercial use, reference data is updated daily, and storing/caching rates is encouraged. Read the [provider FAQ and terms](https://frankfurter.dev/) before choosing a rate source for regulated reporting.

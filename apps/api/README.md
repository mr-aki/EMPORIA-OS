# Emporia OS API

The first executable backend slice: authenticated venture CRUD, workspace scoping, readiness/liveness checks, and an append-only application audit trail.

## Run locally

Requires Python 3.12+.

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export EMPORIA_API_TOKEN="local-development-token-change-this"
uvicorn emporia_api.main:app --reload
```

OpenAPI docs: http://localhost:8000/docs

```bash
curl http://localhost:8000/health/ready
curl -H "Authorization: Bearer local-development-token-change-this" http://localhost:8000/api/v1/ventures
```

## Docker

From the repository root:

```bash
cp .env.example .env
# Set a unique EMPORIA_API_TOKEN in .env
docker compose up --build
```

## Configuration

All settings use the `EMPORIA_` prefix. The initial deployment model is one isolated workspace per API deployment. The workspace identifier is server-side configuration; clients cannot select another tenant by supplying a header or request field. Use a unique API token per deployment and terminate TLS at a trusted reverse proxy before exposing the service.

SQLite is the zero-dependency local default. Set `EMPORIA_DATABASE_URL` to a PostgreSQL SQLAlchemy URL for a shared deployment; production migration management and multi-user identity are subsequent milestones, not claimed in this slice.

## API

- `GET /health/live` and `GET /health/ready`
- `POST /api/v1/ventures`
- `GET /api/v1/ventures`
- `GET /api/v1/ventures/{id}`
- `PATCH /api/v1/ventures/{id}`
- `DELETE /api/v1/ventures/{id}`
- `GET /api/v1/audit-events`

All venture and audit routes require a bearer token. Mutations create audit events in the same database transaction.


## AI provider gateway

The API includes an authenticated, server-side text-generation gateway for:

- **OpenAI** via the Chat Completions REST endpoint.
- **Anthropic Claude** via the Messages API.
- **Google Gemini** via `generateContent`.
- **OpenAI-compatible endpoints**, including operator-managed local model servers such as Ollama.

Configure keys in the API process environment (or a deployment secrets manager):

```bash
export EMPORIA_OPENAI_API_KEY="..."
export EMPORIA_ANTHROPIC_API_KEY="..."
export EMPORIA_GEMINI_API_KEY="..."
```

For a local OpenAI-compatible server, configure its server-side base URL:

```bash
export EMPORIA_OPENAI_COMPATIBLE_BASE_URL="http://127.0.0.1:11434/v1"
# API key is optional for local servers that do not require one.
export EMPORIA_OPENAI_COMPATIBLE_API_KEY=""
```

In Docker, `127.0.0.1` refers to the API container itself. Use a service name on the Compose network or a host address reachable from the container.

Authenticated endpoints:

- `GET /api/v1/ai/providers` returns configured provider names and safe capability metadata, never credentials.
- `POST /api/v1/ai/chat` sends a bounded text chat request and returns normalized content and token usage.

Example request:

```bash
curl -X POST http://localhost:8000/api/v1/ai/chat \\
  -H "Authorization: Bearer $EMPORIA_API_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "provider": "openai",
    "model": "gpt-5",
    "messages": [{"role": "user", "content": "Summarize my launch checklist."}],
    "max_tokens": 500
  }'
```

**Credential distinction:** provider API keys are separate from ChatGPT, Claude, or Gemini consumer subscriptions. This gateway makes direct server-to-server API calls and uses the API billing/quotas of the configured provider account. Never put provider keys in browser code, source control, agent prompts, or request payloads.

The gateway does not execute model-generated tools or business actions. Autonomous agent execution, approvals, budgets, retries, and tool sandboxing are separate layers that must be implemented before allowing bots to act on connected business systems.


## Specialist agent runtime

Eight reviewed specialist definitions are currently registered and share the authenticated, persisted agent-run execution path:

- `commerce-strategist`: business model, positioning, validation strategy, and launch decisions.
- `product-research-analyst`: opportunity assessment, customer problems, evidence quality, and assortment risk.
- `growth-marketing-planner`: channel strategy, funnel design, and measurable acquisition experiments.
- `pricing-unit-economics-analyst`: price floors, contribution margin, break-even analysis, and scenario modelling.
- `supplier-sourcing-analyst`: sourcing briefs, RFQs, supplier due diligence, quality planning, and landed-cost inputs.
- `customer-voice-analyst`: customer feedback themes, evidence traceability, journey friction, and prioritised fixes.
- `marketplace-listing-optimizer`: product listings, marketplace SEO, merchandising briefs, and claim checks.
- `retention-lifecycle-specialist`: activation, post-purchase, repeat-purchase, loyalty, and win-back journeys.

Authenticated endpoints:

- `GET /api/v1/agents` lists public agent metadata. Private system prompts are not exposed.
- `POST /api/v1/agents/{agent_id}/runs` executes a specialist through one configured provider.
- `GET /api/v1/agent-runs` lists persisted runs for the configured workspace.
- `GET /api/v1/agent-runs/{run_id}` retrieves one run.

Example:

```bash
curl -X POST http://localhost:8000/api/v1/agents/commerce-strategist/runs \\
  -H "Authorization: Bearer $EMPORIA_API_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "provider": "openai",
    "model": "gpt-5",
    "task": "Design a 30-day validation plan for a niche home organization store.",
    "max_tokens": 1800
  }'
```

The server enforces a configurable per-run output-token ceiling with `EMPORIA_AGENT_MAX_OUTPUT_TOKENS` (default: 2048; allowed range: 1–4096). Requests above this ceiling are rejected before a run is created or a provider is called. This is a per-request output bound, not a monthly monetary budget or a complete rate/concurrency limiter.

Runs persist their task, output, status, token usage, provider request ID, and timestamps. Start/completion/failure events are added to the audit log. Known upstream failures and unexpected research/provider exceptions transition the run to a terminal failed state; unexpected exception details are not returned to API clients.

**Agent contract:** `GET /api/v1/agents` also returns each specialist's category, expected deliverables, required context, version, and expertise. Internal system prompts remain private. All eight specialists execute through the same provider and run-history pipeline; newly added specialists are covered by endpoint-level execution tests.

**Execution boundary:** these agents are advisory text agents. They do not have browser access, shell access, store-admin credentials, payment access, or action tools. They cannot autonomously change a live business. The next runtime milestones are queued/background execution, scoped tool grants, human approval gates, budget enforcement, and sandboxed integrations.


## Network research connector

Emporia can retrieve fresh, extracted web context through the official [Brave Search LLM Context API](https://api-dashboard.search.brave.com/documentation/services/llm-context).

Configure a Brave Search API key on the API server:

```bash
export EMPORIA_BRAVE_SEARCH_API_KEY="..."
```

Or add `EMPORIA_BRAVE_SEARCH_API_KEY` to the deployment secret store / local `.env` file. The key is never accepted from browsers or agent request bodies and is never returned by the API.

Authenticated research endpoint:

```bash
curl -X POST http://localhost:8000/api/v1/research/search \\
  -H "Authorization: Bearer $EMPORIA_API_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "query": "2026 ecommerce returns trends official industry report",
    "maximum_number_of_tokens": 4000
  }'
```

An agent can explicitly include network research:

```bash
curl -X POST http://localhost:8000/api/v1/agents/product-research-analyst/runs \\
  -H "Authorization: Bearer $EMPORIA_API_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "provider": "openai",
    "model": "gpt-5",
    "task": "Assess the demand and operational risks for a reusable home storage product.",
    "web_research": true,
    "research_query": "reusable home storage ecommerce demand customer complaints 2026",
    "max_tokens": 1800
  }'
```

**Privacy:** `research_query` is a separate, explicit field. Emporia never sends the full task or its private business context to Brave automatically. Only the supplied research query is sent to the external search provider. Use a general query and exclude customer personal data, credentials, confidential supplier terms, and other private material.

The response contains source URLs, titles, hostnames, excerpts, and available page-age metadata. Agent run history stores the selected source evidence alongside the output so results can be reviewed later. Retrieved page text is untrusted external data; it is passed to the model as reference context, not as system instructions.

**External dependency:** a valid Brave Search API key and active API entitlement are required for live searches. CI uses mocked HTTP responses and does not consume paid API requests. Respect the provider's quotas and rate limits. Search results are evidence to evaluate, not a guarantee that every source is accurate or authoritative.

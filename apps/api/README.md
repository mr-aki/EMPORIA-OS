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

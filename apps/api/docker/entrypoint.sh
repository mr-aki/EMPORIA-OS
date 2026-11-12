#!/bin/sh
set -eu

alembic upgrade head
exec uvicorn emporia_api.main:app --host 0.0.0.0 --port 8000

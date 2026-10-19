#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

export TEST_MYSQL_HOST="${TEST_MYSQL_HOST:-127.0.0.1}"
export TEST_MYSQL_PORT="${TEST_MYSQL_PORT:-3307}"
export TEST_MYSQL_USER="${TEST_MYSQL_USER:-moyo}"
export TEST_MYSQL_PASSWORD="${TEST_MYSQL_PASSWORD:-moyo_dev_password}"
export TEST_MYSQL_DATABASE="${TEST_MYSQL_DATABASE:-moyo_test_e2e}"

uv run python tests/e2e/prepare_node_e2e.py

export PUBLIC_BASE_URL="http://127.0.0.1:8050"
export DATABASE_URL="${TEST_DATABASE_URL:-mysql+aiomysql://${TEST_MYSQL_USER}:${TEST_MYSQL_PASSWORD}@${TEST_MYSQL_HOST}:${TEST_MYSQL_PORT}/${TEST_MYSQL_DATABASE}?charset=utf8mb4}"
export SECRET_KEY="node-e2e-secret"
export PHONE_HMAC_KEY="node-e2e-phone-hmac"
export PHONE_ENCRYPTION_KEY="WbHjoN9iR54PDbJDatQC0i2G-ow1XNn2_AzRpfdo3_0="
export IDENTITY_ENCRYPTION_KEY="odEQ9io8t2uipKkgvVyIY3UXIYGua3wrE8fnS3662sE="
export ADMIN_USERNAME="admin"
export ADMIN_INITIAL_PASSWORD="integration-admin-password"
export JATOS_BASE_URL="${JATOS_BASE_URL:-http://127.0.0.1:9000}"
export JATOS_STUDY_CODE="${JATOS_STUDY_CODE:-node-e2e}"
export COOKIE_SECURE="false"
export SERVE_FRONTEND="true"
export LOGIN_RATE_LIMIT_ATTEMPTS="1000"
export PYTHONUNBUFFERED="1"

exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8050 --workers 1

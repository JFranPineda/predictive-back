#!/usr/bin/env bash
# First start of the installation's PostgreSQL (v4 Phase 6). The application
# connects as an ordinary role that owns its two databases and nothing else,
# as on the bench (deploy/onprem-test/init.sql).
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username postgres --dbname postgres \
  -v password="$PREDICTIVE_DB_PASSWORD" -v tenant_db="predictive_$TENANT" <<'SQL'
CREATE ROLE predictive_app LOGIN PASSWORD :'password';
CREATE DATABASE predictive_control OWNER predictive_app;
CREATE DATABASE :"tenant_db" OWNER predictive_app;
SQL

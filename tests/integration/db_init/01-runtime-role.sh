#!/bin/sh
set -eu

: "${TEST_DATABASE_RUNTIME_PASSWORD:?Set TEST_DATABASE_RUNTIME_PASSWORD in .env}"

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set="runtime_password=$TEST_DATABASE_RUNTIME_PASSWORD" <<'SQL'
CREATE ROLE document_insight_test_runtime LOGIN PASSWORD :'runtime_password' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE document_insight_test TO document_insight_test_runtime;
GRANT USAGE ON SCHEMA public TO document_insight_test_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE document_insight_test_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO document_insight_test_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE document_insight_test_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO document_insight_test_runtime;
SQL

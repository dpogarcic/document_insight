#!/bin/sh
# Write PgBouncer's plain-auth userlist from the same restricted-role passwords
# already used to build DATABASE_*_URL in .env. PgBouncer authenticates each
# client against this file, then opens the backend PostgreSQL connection as
# that same login role, so PostgreSQL's own per-role grants and RLS policies
# apply unchanged; PgBouncer only multiplexes connections, it does not widen
# access. di_profile_operator_login is optional, matching bootstrap_roles.py.
set -eu

out="/run/pgbouncer/userlist.txt"
umask 077

{
    printf '"%s" "%s"\n' "di_api_read_login" "$DATABASE_READ_PASSWORD"
    printf '"%s" "%s"\n' "di_api_write_login" "$DATABASE_WRITE_PASSWORD"
    printf '"%s" "%s"\n' "di_auth_login" "$DATABASE_AUTH_PASSWORD"
    printf '"%s" "%s"\n' "di_worker_login" "$DATABASE_WORKER_PASSWORD"
    printf '"%s" "%s"\n' "di_reconciler_login" "$DATABASE_RECONCILER_PASSWORD"
    printf '"%s" "%s"\n' "di_monitor_login" "$DATABASE_MONITOR_PASSWORD"
    if [ -n "${DATABASE_PROFILE_OPERATOR_PASSWORD:-}" ]; then
        printf '"%s" "%s"\n' "di_profile_operator_login" "$DATABASE_PROFILE_OPERATOR_PASSWORD"
    fi
} > "$out"

chmod 0444 "$out"

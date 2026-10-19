#!/usr/bin/env bash
# On-premise test bench (predictive-docs docs/v4, Phase 0).
#
# PREDICTIVE against a disposable PostgreSQL 16 and a throwaway tenant,
# `ipsa_test`. It never touches data/ nor the development tenants: every
# setting it needs is exported here, and exported variables win over .env
# (python-dotenv does not override what is already set).
#
#   scripts/onprem_test.sh up          database, control plane, tenant, licence
#   scripts/onprem_test.sh import      IPSA's 47 books into the bench tenant
#   scripts/onprem_test.sh start       API on 127.0.0.1:8013, in the background
#   scripts/onprem_test.sh smoke       checks against the running API
#   scripts/onprem_test.sh stop        stop the API
#   scripts/onprem_test.sh down        stop the API and the database, keep data
#   scripts/onprem_test.sh reset       down, then delete the database and files
#   scripts/onprem_test.sh manage ...  any manage.py command with the bench env
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PG_PORT="${ONPREM_TEST_PG_PORT:-5437}"
API_PORT="${ONPREM_TEST_API_PORT:-8013}"
TENANT=ipsa_test
STATE="$ROOT/.onprem-test"
KEYS="$STATE/keys"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
APP_URL="postgres://predictive_app:onprem-test@127.0.0.1:$PG_PORT"
COMPOSE=(docker compose -f deploy/onprem-test/compose.yml)

bench_env() {
  export DJANGO_SETTINGS_MODULE=config.settings.dev
  export CONTROL_DATABASE_URL="$APP_URL/predictive_control"
  export DEFAULT_TENANT="$TENANT"
  export SECRET_KEY=onprem-test-only
  # The bench signs with its own throwaway key, never ours, and the API holds
  # only its public half (dev settings read it from here). No v1 secret.
  export LICENSE_SECRET=
  if [[ -f "$KEYS/public.key" ]]; then
    LICENSE_PUBLIC_KEY="$(cat "$KEYS/public.key")"
    export LICENSE_PUBLIC_KEY
  fi
  export ALLOWED_HOSTS=127.0.0.1,localhost
  export MEDIA_BACKEND=local
  export MEDIA_ROOT=.onprem-test/media
  export HISTORY_ROOT=.onprem-test/history
  export BASE_DOMAIN=
  # A tenant URL in .env would win over the bench registry and send a request
  # to a development database. Exported empty, .env can no longer set it.
  if [[ -f .env ]]; then
    while IFS= read -r key; do export "$key="; done \
      < <(grep -oE '^TENANT_[A-Z0-9_]+_DATABASE_URL' .env || true)
  fi
}

manage() {
  bench_env
  "$PYTHON" manage.py "$@"
}

psql_app() {
  "${COMPOSE[@]}" exec -T -e PGPASSWORD=onprem-test db \
    psql -h 127.0.0.1 -U predictive_app -d "${2:-predictive_ipsa_test}" -tAc "$1"
}

# Encrypted like ours, with a password that exists only in the bench.
bench_keys() {
  [[ -f "$KEYS/signing-key.pem" ]] && return
  mkdir -p "$KEYS"
  chmod 700 "$KEYS"
  (umask 077 && "$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(24))' >"$KEYS/password")
  manage license keygen --signing-key "$KEYS/signing-key.pem" \
    --password-file "$KEYS/password" --public-key "$KEYS/public.key"
}

up() {
  mkdir -p "$STATE"
  bench_keys
  "${COMPOSE[@]}" up -d --wait
  manage migrate --database=default --verbosity 0
  manage tenants add "$TENANT" "IPSA — banco on-premise" \
    --url "$APP_URL/predictive_ipsa_test" --deployment on_premise
  manage tenants migrate "$TENANT" >/dev/null
  # No `modules bootstrap` here: on an empty database the auto-installed
  # modules need a catalogue (units, magnitudes, statuses) that only the
  # importer lays down today. `import` runs it after the catalogue exists.
  # Also when the bench still holds a v1 licence from before Phase 1.
  if ! manage tenants list | grep -E " $TENANT " | grep -q " v2"; then
    manage tenants issue "$TENANT" --signing-key "$KEYS/signing-key.pem" \
      --password-file "$KEYS/password" --plan gestionado --months 3 --grace 30 \
      --equipment 650 --users 40 --plants 1 | head -1
  fi
  manage tenants list
}

import_books() {
  local docs="${1:-../predictive-docs}"
  manage tenants run "$TENANT" import_ipsa --docs "$docs" --no-images \
    --report .onprem-test/ipsa-import-report.md
  manage tenants run "$TENANT" modules bootstrap
}

start() {
  mkdir -p "$STATE"
  if [[ -f "$STATE/api.pid" ]] && kill -0 "$(cat "$STATE/api.pid")" 2>/dev/null; then
    echo "La API del banco ya corre (pid $(cat "$STATE/api.pid"))"
    return
  fi
  if ss -ltnH "( sport = :$API_PORT )" | grep -q .; then
    echo "El puerto $API_PORT está ocupado por otro proceso" >&2
    exit 1
  fi
  bench_env
  setsid "$PYTHON" manage.py runserver "127.0.0.1:$API_PORT" --noreload \
    >"$STATE/api.log" 2>&1 &
  echo $! >"$STATE/api.pid"
  for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null -H "X-Tenant: $TENANT" \
      "http://127.0.0.1:$API_PORT/api/v1/license/status/" 2>/dev/null; then
      echo "API del banco en http://127.0.0.1:$API_PORT"
      return
    fi
    sleep 0.5
  done
  echo "La API no respondió; ver $STATE/api.log" >&2
  exit 1
}

stop() {
  [[ -f "$STATE/api.pid" ]] || return 0
  local pid
  pid="$(cat "$STATE/api.pid")"
  # Its own process group (setsid), so the whole tree goes at once.
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  rm -f "$STATE/api.pid"
}

smoke() {
  local base="http://127.0.0.1:$API_PORT/api/v1"
  local failed=0 body code value

  pass() { echo "  ✓ $1"; }
  fail() { echo "  ✗ $1"; failed=1; }

  echo "Licencia"
  body="$(curl -fsS -H "X-Tenant: $TENANT" "$base/license/status/" 2>/dev/null || true)"
  if "$PYTHON" -c 'import json, sys
d = json.loads(sys.argv[1])
sys.exit(0 if d.get("status") == "active" and d.get("deployment") == "on_premise" else 1)' \
    "$body" 2>/dev/null; then
    pass "status/ responde active para $TENANT (on_premise)"
  else
    fail "status/ no responde active: ${body:-sin respuesta}"
  fi

  echo "Firma"
  signing_checks

  echo "Aislamiento"
  code="$(curl -s -o /dev/null -w '%{http_code}' -H "X-Tenant: ambev" "$base/license/status/")"
  if [[ "$code" == "404" ]]; then
    pass "el banco no conoce al inquilino ambev (HTTP 404)"
  else
    fail "el banco respondió $code para ambev: podría estar viendo una base de desarrollo"
  fi

  echo "PostgreSQL"
  value="$(psql_app "select current_setting('server_version_num')::int >= 160000" || true)"
  [[ "$value" == "t" ]] && pass "PostgreSQL 16 o superior" || fail "PostgreSQL menor que 16: $value"
  value="$(psql_app "select rolsuper from pg_roles where rolname = current_user" || true)"
  [[ "$value" == "f" ]] && pass "la aplicación entra con un rol sin superusuario" \
    || fail "el rol de la aplicación es superusuario"
  # The installation fingerprint of Phase 2 reads this. Reported, not
  # required: if the plain role cannot read it, Phase 2 needs a GRANT.
  if value="$(psql_app "select system_identifier from pg_control_system()" 2>&1)"; then
    pass "el rol lee system_identifier ($value)"
  else
    echo "  ! el rol no lee system_identifier: la Fase 2 necesitará un GRANT ($value)"
  fi

  echo "Datos"
  value="$(psql_app "select count(*) from assets_assetgroup" || echo 0)"
  if [[ "$value" == "0" ]]; then
    echo "  · sin libros importados (scripts/onprem_test.sh import)"
  else
    value="$(psql_app "select (select count(*) from assets_assetgroup) || '/' ||
      (select count(*) from assets_equipment) || '/' ||
      (select count(*) from assets_measurementpoint) || '/' ||
      (select count(*) from measurements_reading)")"
    [[ "$value" == "47/98/795/10536" ]] \
      && pass "IPSA completo: 47 conjuntos, 98 equipos, 795 puntos, 10 536 lecturas" \
      || fail "conteos distintos de la planta IPSA (conjuntos/equipos/puntos/lecturas): $value"
  fi

  return "$failed"
}

# Phase 1: the signing key is encrypted and stays out of the API, and the
# API resolves the licence with the public key alone.
signing_checks() {
  local before licences out status pid
  value="$(head -1 "$KEYS/signing-key.pem" 2>/dev/null || true)"
  if [[ "$value" == "-----BEGIN ENCRYPTED PRIVATE KEY-----" \
    && "$(stat -c %a "$KEYS/signing-key.pem")" == "600" ]]; then
    pass "la clave de firma está cifrada y solo la lee su dueño"
  else
    fail "la clave de firma no está cifrada o la leen otros: ${value:-sin archivo}"
  fi

  before="$(sha256sum "$KEYS/signing-key.pem" 2>/dev/null || true)"
  if manage license keygen --signing-key "$KEYS/signing-key.pem" --password-file "$KEYS/password" \
    --public-key "$STATE/overwrite.key" >/dev/null 2>&1 \
    || [[ "$(sha256sum "$KEYS/signing-key.pem" 2>/dev/null || true)" != "$before" ]]; then
    fail "keygen pisó una clave de firma existente"
  else
    pass "keygen no pisa una clave de firma existente"
  fi
  rm -f "$STATE/overwrite.key"

  licences="$(psql_app "select count(*) from licensing_licenserecord" predictive_control || true)"
  (umask 077 && echo "not-the-bench-password" >"$STATE/wrong-password")
  out="$(manage tenants issue "$TENANT" --signing-key "$KEYS/signing-key.pem" \
    --password-file "$STATE/wrong-password" 2>&1)" && status=0 || status=$?
  rm -f "$STATE/wrong-password"
  if [[ $status -ne 0 && "$out" == *"contraseña incorrecta"* \
    && "$(psql_app "select count(*) from licensing_licenserecord" predictive_control)" == "$licences" ]]; then
    pass "con otra contraseña no se emite nada"
  else
    fail "emitir con otra contraseña no falló con claridad (salida $status): ${out:0:200}"
  fi

  rm -rf "$STATE/foreign" && mkdir -p "$STATE/foreign"
  (umask 077 && echo "a-foreign-bench-password" >"$STATE/foreign/password")
  out="$(manage license keygen --signing-key "$STATE/foreign/signing-key.pem" \
    --password-file "$STATE/foreign/password" --public-key "$STATE/foreign/public.key" 2>&1 \
    && manage tenants issue "$TENANT" --signing-key "$STATE/foreign/signing-key.pem" \
      --password-file "$STATE/foreign/password" 2>&1)" && status=0 || status=$?
  rm -rf "$STATE/foreign"
  if [[ $status -ne 0 && "$out" == *"no corresponde"* \
    && "$(psql_app "select count(*) from licensing_licenserecord" predictive_control)" == "$licences" ]]; then
    pass "una clave de firma ajena a la pública instalada no emite"
  else
    fail "una clave ajena emitió o falló sin explicarlo (salida $status): ${out:0:200}"
  fi

  if manage tenants list | grep -E " $TENANT " | grep -q " v2"; then
    pass "la licencia vigente de $TENANT es v2 (Ed25519)"
  else
    fail "la licencia vigente de $TENANT no es v2"
  fi

  pid="$(cat "$STATE/api.pid" 2>/dev/null || true)"
  out="$(tr '\0' '\n' <"/proc/${pid:-0}/environ" 2>/dev/null || true)"
  if [[ -n "$out" ]] && grep -qE '^LICENSE_PUBLIC_KEY=.+' <<<"$out" \
    && ! grep -qE '^LICENSE_SECRET=.+' <<<"$out" && ! grep -q 'signing-key' <<<"$out"; then
    pass "la API resuelve la licencia con la clave pública sola"
  else
    fail "la API corre con algo más que la clave pública (o no corre)"
  fi

  # A PEM block opens its line; a quoted header in a test or here does not.
  if git -C "$ROOT" grep -qIE '^-----BEGIN [A-Z ]*PRIVATE KEY-----'; then
    fail "hay una clave privada versionada en el repo"
  else
    pass "ninguna clave privada versionada en el repo"
  fi
}

down() {
  stop
  "${COMPOSE[@]}" stop
}

reset() {
  stop
  "${COMPOSE[@]}" down -v
  rm -rf "$STATE"
}

case "${1:-}" in
  up) up ;;
  import) shift; import_books "$@" ;;
  start) start ;;
  smoke) smoke ;;
  stop) stop ;;
  down) down ;;
  reset) reset ;;
  manage) shift; manage "$@" ;;
  *) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

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
#
# The renewal checks also start the renewal service from ../predictive-renewal
# on 127.0.0.1:8014 when that repository is there (ONPREM_RENEWAL_DIR).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PG_PORT="${ONPREM_TEST_PG_PORT:-5437}"
API_PORT="${ONPREM_TEST_API_PORT:-8013}"
RENEWAL_PORT="${ONPREM_TEST_RENEWAL_PORT:-8014}"
RENEWAL_DIR="${ONPREM_RENEWAL_DIR:-$ROOT/../predictive-renewal}"
TENANT=ipsa_test
STATE="$ROOT/.onprem-test"
KEYS="$STATE/keys"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
APP_URL="postgres://predictive_app:onprem-test@127.0.0.1:$PG_PORT"
COMPOSE=(docker compose -f deploy/onprem-test/compose.yml)
SIGN=(--signing-key "$KEYS/signing-key.pem" --password-file "$KEYS/password")
TERMS=(--plan gestionado --grace 30 --equipment 650 --users 40 --plants 1)

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
  export INSTALLATION_FILE=.onprem-test/installation.json
  # No renewal service unless a check sets one: the bench never goes online.
  export LICENSE_RENEW_URL=
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
  # Also when the bench still holds a licence from before Phase 1 or 2.
  if ! manage tenants list | grep -E " $TENANT " | grep -q " v2 · inst "; then
    manage tenants issue "$TENANT" "${SIGN[@]}" "${TERMS[@]}" --months 3 \
      --installation "$(manage license fingerprint --tenant "$TENANT" --code)" | head -1
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

  echo "Instalación y reloj"
  installation_checks

  echo "Renovación"
  renewal_checks

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

# Our issuing machine, played by its own control plane: a licence signed
# there is not stored in the customer's until it is loaded.
issuer() {
  # A subshell, and after bench_env: it exports the bench's own control plane.
  (bench_env && export CONTROL_DATABASE_URL="sqlite:///$STATE/issuer.sqlite3" && "$PYTHON" manage.py "$@")
}

issuer_ready() {
  [[ -f "$STATE/issuer.sqlite3" ]] && return
  issuer migrate --database=default --verbosity 0
  issuer tenants add "$TENANT" "IPSA — banco on-premise" \
    --url "$APP_URL/predictive_ipsa_test" --deployment on_premise >/dev/null
}

# Months that take a new licence past the one in force, however far earlier
# runs of these checks have pushed it.
past_current() {
  echo $(( $(field "$(api_status)" days_left) / 28 + 2 ))
}

# manage with the renewal service configured: after bench_env, which empties it.
online_manage() {
  local url="$1"
  shift
  (bench_env && export LICENSE_RENEW_URL="$url" && "$PYTHON" manage.py "$@")
}

licences() { psql_app "select count(*) from licensing_licenserecord" predictive_control; }

# What the API answers right now, through the whole middleware.
api_status() {
  curl -s -H "X-Tenant: $TENANT" "http://127.0.0.1:$API_PORT/api/v1/license/status/"
}

# A write the licence gate judges before anything else: 402 when it refuses,
# 401 (no credentials) when it lets it through. It never writes.
write_gate() {
  curl -s -o /dev/null -w '%{http_code}' -X PUT -H "X-Tenant: $TENANT" \
    -H "Content-Type: application/json" -d '{"language":"es"}' \
    "http://127.0.0.1:$API_PORT/api/v1/users/me/language/"
}

field() { "$PYTHON" -c 'import json, sys; print(json.loads(sys.argv[1]).get(sys.argv[2], ""))' "$1" "$2"; }

# The verdict the service builds for a request, from a shell. `$1` shifts the
# clock by that many hours (freezegun): that is how the remembered date is
# pushed ahead of the real clock, which the API then sees as behind.
verdict_at() {
  manage shell --verbosity 0 -c "
from datetime import UTC, datetime, timedelta
from freezegun import freeze_time
from modules.licensing.application.license_service import current_verdict
from modules.licensing.infrastructure.keys import trusted_keys
with freeze_time(datetime.now(UTC) + timedelta(hours=${1:-0})):
    print('VERDICT', current_verdict('$TENANT', keys=trusted_keys()).status.value)
" 2>&1 | grep '^VERDICT' | cut -d' ' -f2
}

# Phase 2: which installation the licence covers (two of three), and a
# remembered date that a clock more than a day behind turns into read-only.
installation_checks() {
  local here out body file_id db_id resets
  here="$(manage license fingerprint --tenant "$TENANT" --code 2>/dev/null || true)"
  out="$(manage license fingerprint --tenant "$TENANT" 2>&1 || true)"
  if [[ "$here" =~ ^[0-9a-f-]{36}:[0-9a-f]{32}:[0-9a-f]{32}$ ]] && grep -q "PostgreSQL" <<<"$out"; then
    pass "license fingerprint da los tres datos: instalación, PostgreSQL y máquina"
  else
    fail "license fingerprint no da los tres datos: ${here:-$out}"
  fi

  file_id="$("$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1]))["installation_id"])' \
    "$STATE/installation.json" 2>/dev/null || true)"
  db_id="$(psql_app "select installation_id from licensing_installation" predictive_control || true)"
  if [[ -n "$db_id" && "$file_id" == "$db_id" && "$here" == "$db_id":* ]]; then
    pass "el identificador de instalación está en el plano de control y en el volumen de datos"
  else
    fail "identificador distinto o ausente: control=${db_id:-?} volumen=${file_id:-?}"
  fi

  body="$(api_status)"
  if manage tenants list | grep -E " $TENANT " | grep -q "· inst ${here:0:8}" \
    && [[ "$(field "$body" status)" == "active" ]]; then
    pass "la licencia está ligada a esta instalación y responde active"
  else
    fail "la licencia no está ligada a esta instalación o no responde active: $body"
  fi

  echo "otra-maquina-$RANDOM" >"$STATE/other-machine-id"
  out="$(MACHINE_ID_FILE="$STATE/other-machine-id" verdict_at 0)"
  rm -f "$STATE/other-machine-id"
  [[ "$out" == "active" ]] && pass "con otra máquina sigue active: 2 de 3 alcanzan" \
    || fail "con otra máquina responde ${out:-nada}"

  [[ "$(verdict_at 12)" == "active" && "$(field "$(api_status)" status)" == "active" ]] \
    && pass "un reloj 12 h por debajo de la fecha recordada no cambia nada" \
    || fail "12 h por debajo ya cambia el veredicto"

  verdict_at 48 >/dev/null
  body="$(api_status)"
  if [[ "$(field "$body" status)" == "clock_behind" && "$(write_gate)" == "402" \
    && "$(field "$body" reason)" == *"hora del servidor"* ]]; then
    pass "48 h por debajo: solo lectura, y explica qué fecha corregir"
  else
    fail "48 h por debajo no pasa a solo lectura con su motivo: $body"
  fi
  [[ "$(verdict_at 48)" == "active" ]] && pass "con la fecha corregida vuelve a active" \
    || fail "con la fecha corregida no vuelve a active"

  resets="$(psql_app "select count(*) from licensing_licenseevent where kind = 'clock_reset'" predictive_control)"
  manage license clock reset --tenant "$TENANT" >/dev/null 2>&1 || true
  if [[ "$(field "$(api_status)" status)" == "active" && "$(psql_app \
    "select count(*) from licensing_licenseevent where kind = 'clock_reset'" predictive_control)" \
    -gt "$resets" ]]; then
    pass "license clock reset devuelve el sistema a active y queda registrado"
  else
    fail "license clock reset no lo devolvió a active o no quedó registrado"
  fi

  # Another installation: same installation id, another cluster and machine.
  manage tenants issue "$TENANT" "${SIGN[@]}" "${TERMS[@]}" --months "$(past_current)" \
    --installation "${here%%:*}:$(printf 'a%.0s' {1..32}):$(printf 'b%.0s' {1..32})" >/dev/null
  body="$(api_status)"
  if [[ "$(field "$body" status)" == "other_installation" && "$(write_gate)" == "402" \
    && "$(field "$body" reason)" == *"license fingerprint"* ]]; then
    pass "una licencia de otra instalación: solo lectura y cómo reactivarla"
  else
    fail "una licencia de otra instalación no se trata como tal: $body"
  fi

  # The remembered date pushed 48 h ahead under the licence in force: the
  # reissued one is active only if a new licence starts the date again.
  verdict_at 48 >/dev/null
  manage tenants reissue "$TENANT" "${SIGN[@]}" --installation "$here" >/dev/null
  body="$(api_status)"
  if [[ "$(field "$body" status)" == "active" && "$(write_gate)" == "401" ]]; then
    pass "reactivada con una licencia nueva para esta instalación, que además reinicia la fecha"
  else
    fail "la reactivación no la deja active: $body"
  fi

  # Both copies edited the way a flipped byte would: same signature, the year
  # moved to 2096. Trusted, that would be seventy years of read-only.
  manage shell --verbosity 0 -c "
from modules.licensing.infrastructure.installation import read_state, write_state
from modules.licensing.infrastructure.models import Tenant
tenant = Tenant.objects.get(code='$TENANT')
Tenant.objects.filter(pk=tenant.pk).update(clock={**tenant.clock, 'seen_at': '2096' + tenant.clock['seen_at'][4:]})
state = read_state()
copy = state['clocks']['$TENANT']
write_state({**state, 'clocks': {**state['clocks'], '$TENANT': {**copy, 'seen_at': '2096' + copy['seen_at'][4:]}}})
"
  body="$(api_status)"
  if [[ "$(field "$body" status)" == "active" ]] && ! psql_app \
    "select clock->>'seen_at' from licensing_tenant where code = '$TENANT'" predictive_control | grep -q '^2096'; then
    pass "una fecha recordada ilegible se ignora y se vuelve a escribir: sigue active"
  else
    fail "una fecha recordada ilegible cambió el veredicto o no se rehízo: $body"
  fi
}

# Phase 3: the request that leaves the network, loading a .lic, and the
# daily check against the renewal service.
renewal_checks() {
  local here text body before after out status file count token
  here="$(manage license fingerprint --tenant "$TENANT" --code 2>/dev/null || true)"
  text="$(manage license request --tenant "$TENANT" 2>/dev/null || true)"
  if [[ "$(sed -n '1p' <<<"$text")" == "PREDICTIVE · solicitud de licencia" \
    && "$(cut -d: -f1 <<<"$text" | tail -n +2 | paste -sd,)" == "cliente,licencia,vence,instalación,versión,equipos,usuarios" \
    && "$text" == *"instalación: $here"* && "$text" =~ equipos:\ [0-9]+ \
    && "$text" =~ versión:\ [0-9]+\.[0-9]+ ]]; then
    pass "la solicitud dice exactamente qué sale: cliente, licencia, instalación, versión y dos conteos"
  else
    fail "la solicitud no es la esperada: ${text:-sin salida}"
  fi

  issuer_ready
  before="$(field "$(api_status)" days_left)"
  file="$STATE/renewal.lic"
  rm -f "$file"
  issuer tenants issue "$TENANT" "${SIGN[@]}" "${TERMS[@]}" --months "$(past_current)" \
    --installation "$here" --out "$file" >/dev/null
  count="$(licences)"
  out="$(manage license import "$file" --tenant "$TENANT" 2>&1)" && status=0 || status=$?
  after="$(field "$(api_status)" days_left)"
  if [[ $status -eq 0 && "$after" -gt "$before" && "$(licences)" -gt "$count" \
    && "$(field "$(api_status)" status)" == "active" ]]; then
    pass "un .lic válido extiende la vigencia ($before → $after días) sin reiniciar la API"
  else
    fail "cargar un .lic válido no extendió la vigencia (salida $status): ${out:0:200}"
  fi

  count="$(licences)"
  out="$(manage license import "$file" --tenant "$TENANT" 2>&1)" && status=0 || status=$?
  [[ $status -eq 0 && "$out" == *"ya está cargada"* && "$(licences)" == "$count" ]] \
    && pass "cargar dos veces el mismo .lic no duplica nada" \
    || fail "cargar dos veces el mismo .lic: ${out:0:200}"

  rm -f "$STATE/foreign.lic"
  issuer tenants issue "$TENANT" "${SIGN[@]}" "${TERMS[@]}" --months "$(past_current)" \
    --installation "${here%%:*}:$(printf 'c%.0s' {1..32}):$(printf 'd%.0s' {1..32})" \
    --out "$STATE/foreign.lic" >/dev/null
  out="$(manage license import "$STATE/foreign.lic" --tenant "$TENANT" 2>&1)" && status=0 || status=$?
  [[ $status -ne 0 && "$out" == *"otra instalación"* && "$(licences)" == "$count" ]] \
    && pass "un .lic de otra instalación se rechaza y dice por qué" \
    || fail "un .lic de otra instalación no se rechazó con claridad (salida $status): ${out:0:200}"

  # A character in the middle of the signature: the last one of a base64
  # signature carries only padding bits, and changing it may change nothing.
  token="$(grep -v '^#' "$file")"
  "$PYTHON" -c 'import sys
body, _, sig = sys.argv[1].partition(".")
sig = sig[:20] + ("B" if sig[20] != "B" else "C") + sig[21:]
print(f"{body}.{sig}")' "$token" >"$STATE/tampered.lic"
  out="$(manage license import "$STATE/tampered.lic" --tenant "$TENANT" 2>&1)" && status=0 || status=$?
  rm -f "$STATE/foreign.lic" "$STATE/tampered.lic"
  [[ $status -ne 0 && "$out" == *"firma"* && "$(licences)" == "$count" ]] \
    && pass "un .lic con la firma alterada se rechaza" \
    || fail "un .lic con la firma alterada no se rechazó (salida $status): ${out:0:200}"

  out="$(manage shell --verbosity 0 -c "
import sys
connects = []
sys.addaudithook(lambda event, args: connects.append(args[1]) if event == 'socket.connect' else None)
from modules.licensing.infrastructure.tasks import renew_licences
print('RESULT', renew_licences())
print('OUTSIDE', [address for address in connects if not (isinstance(address, tuple) and address[1] == $PG_PORT)])
" 2>&1)"
  [[ "$out" == *"RESULT not_configured"* && "$out" == *"OUTSIDE []"* ]] \
    && pass "sin LICENSE_RENEW_URL la tarea diaria no abre ninguna conexión" \
    || fail "sin LICENSE_RENEW_URL la tarea intentó algo: ${out:0:300}"

  if renewal_http_checks "$here"; then :; fi
  if [[ -d "$RENEWAL_DIR" ]]; then
    online_checks "$here"
  else
    echo "  · sin $RENEWAL_DIR: no se prueba el servidor de renovación"
  fi
}

# Through the API, as the customer's administrator would: only with users,
# which only IPSA's books bring.
renewal_http_checks() {
  local here="$1" base="http://127.0.0.1:$API_PORT/api/v1" admin engineer code file
  manage tenants run "$TENANT" modules upgrade licensing >/dev/null 2>&1 || true
  admin="$(bench_token admin@simiai.pe)"
  if [[ -z "$admin" ]]; then
    echo "  · sin usuarios importados: no se prueba la renovación por la API"
    return 0
  fi
  engineer="$(bench_token carlos.balta@simiai.pe)"

  body="$(curl -s -H "X-Tenant: $TENANT" -H "Authorization: Bearer $admin" "$base/license/renewal/request/")"
  [[ "$(field "$body" text)" == "PREDICTIVE · solicitud de licencia"* ]] \
    && pass "el administrador obtiene la solicitud desde la API" \
    || fail "la API no da la solicitud al administrador: $body"

  file="$STATE/renewal-http.lic"
  rm -f "$file"
  issuer tenants issue "$TENANT" "${SIGN[@]}" "${TERMS[@]}" --months "$(past_current)" \
    --installation "$here" --out "$file" >/dev/null
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "X-Tenant: $TENANT" \
    -H "Authorization: Bearer $engineer" -F "licence=@$file" "$base/license/renew/")"
  [[ "$code" == "403" ]] && pass "sin el permiso de renovar, la API no deja cargar una licencia" \
    || fail "un ingeniero pudo cargar una licencia (HTTP $code)"
  body="$(curl -s -X POST -H "X-Tenant: $TENANT" -H "Authorization: Bearer $admin" \
    -F "licence=@$file" "$base/license/renew/")"
  [[ "$(field "$body" status)" == "renewed" ]] \
    && pass "el administrador carga el .lic desde la API" \
    || fail "la API no cargó el .lic del administrador: $body"

  psql_app "update licensing_tenant set deployment = 'hosted' where code = '$TENANT'" predictive_control >/dev/null
  code="$(curl -s -o /dev/null -w '%{http_code}' -H "X-Tenant: $TENANT" \
    -H "Authorization: Bearer $admin" "$base/license/renewal/request/")"
  body="$(api_status)"
  psql_app "update licensing_tenant set deployment = 'on_premise' where code = '$TENANT'" predictive_control >/dev/null
  [[ "$code" == "404" && "$(field "$body" renewable)" == "False" ]] \
    && pass "en la nube no hay renovación que mostrar (solo on-premise)" \
    || fail "en la nube la renovación sigue a la vista (HTTP $code)"
}

bench_token() {
  curl -s -H "X-Tenant: $TENANT" -H "Content-Type: application/json" \
    -d "{\"email\": \"$1\", \"password\": \"predictive2026\"}" \
    "http://127.0.0.1:$API_PORT/api/v1/auth/login/" | "$PYTHON" -c 'import json, sys
try:
    print(json.load(sys.stdin).get("access", ""))
except ValueError:
    print("")'
}

# The renewal service, run from its own repository with its own database.
renewal_server() {
  (renewal_env && "$RENEWAL_DIR/.venv/bin/python" manage.py "$@")
}

# Its own settings: the bench's exported ones would point it at PREDICTIVE's.
renewal_env() {
  cd "$RENEWAL_DIR" || return 1
  export DJANGO_SETTINGS_MODULE=config.settings SECRET_KEY=onprem-test-only
  export RENEWAL_DATABASE="$STATE/renewal.sqlite3"
  PREDICTIVE_PUBLIC_KEY="$(cat "$KEYS/public.key")"
  export PREDICTIVE_PUBLIC_KEY
}

online_checks() {
  local here="$1" url="http://127.0.0.1:$RENEWAL_PORT/renew" before after out queries file
  renewal_server migrate --verbosity 0
  (renewal_env && setsid "$RENEWAL_DIR/.venv/bin/python" manage.py runserver "127.0.0.1:$RENEWAL_PORT" \
    --noreload >"$STATE/renewal.log" 2>&1 & echo $! >"$STATE/renewal.pid")
  for _ in $(seq 1 40); do
    curl -s -o /dev/null "http://127.0.0.1:$RENEWAL_PORT/admin/login/" && break
    sleep 0.25
  done

  queries="$(psql_app "select count(*) from licensing_renewalquery" predictive_control || echo 0)"
  before="$(field "$(api_status)" days_left)"
  out="$(online_manage "$url" license renew --tenant "$TENANT" 2>&1)"
  [[ "$out" == *"pending"* && "$(field "$(api_status)" days_left)" == "$before" ]] \
    && pass "sin el período pagado, la consulta en línea no cambia nada" \
    || fail "sin el período pagado la consulta hizo algo: ${out:0:200}"

  file="$STATE/paid.lic"
  rm -f "$file"
  issuer tenants issue "$TENANT" "${SIGN[@]}" "${TERMS[@]}" --months "$(past_current)" \
    --installation "$here" --out "$file" >/dev/null
  renewal_server upload_licence "$file" >/dev/null
  out="$(manage shell --verbosity 0 -c "
from django.test import override_settings
from modules.licensing.infrastructure.tasks import renew_licences
with override_settings(LICENSE_RENEW_URL='$url'):
    print('RESULT', renew_licences())
" 2>&1)"
  after="$(field "$(api_status)" days_left)"
  [[ "$out" == *"'$TENANT': 'renewed'"* && "$after" -gt "$before" ]] \
    && pass "con el período pagado, la tarea diaria renueva sola ($before → $after días)" \
    || fail "con el período pagado la tarea no renovó: ${out:0:200}"

  out="$(manage license log --tenant "$TENANT" 2>&1)"
  [[ "$(psql_app "select count(*) from licensing_renewalquery" predictive_control)" -ge $(( queries + 2 )) \
    && "$out" == *"pending"* && "$out" == *"renewed"* && "$out" == *"\"equipment\""* ]] \
    && pass "cada consulta queda registrada con lo que se envió: license log" \
    || fail "las consultas no quedaron en el registro local: ${out:0:300}"

  kill -TERM -- "-$(cat "$STATE/renewal.pid")" 2>/dev/null || kill "$(cat "$STATE/renewal.pid")" 2>/dev/null || true
  rm -f "$STATE/renewal.pid"
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

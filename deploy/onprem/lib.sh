# Shared by the installation's scripts (v4 Phase 6). Sourced, never run.
#
# Everything talks to the installation through Docker Compose from its own
# directory, so the .env written at install time is the single source of what
# runs: images, secrets, names.

INSTALL_DIR="${PREDICTIVE_DIR:-/opt/predictive}"

# The minimum the proposal sells the plans on (doc 07 §2): 4 vCPU, 8 GB, 400 GB.
MIN_CPUS=4
MIN_MEM_KB=7759462          # 7.4 GiB: what a machine sold as 8 GB reports
MIN_DISK_BYTES=380000000000 # a 400 GB disk once formatted

say() { printf '%s\n' "$*"; }
step() { printf '\n▸ %s\n' "$*"; }
warn() { printf 'AVISO: %s\n' "$*" >&2; }
die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

need_root() { [[ $EUID -eq 0 ]] || die "corre este comando con sudo"; }

dc() { (cd "$INSTALL_DIR" && docker compose "$@"); }

# manage.py in a container of its own: works with the services stopped.
manage() { dc run --rm --no-deps -T api python manage.py "$@"; }

env_value() { sed -n "s/^$1=//p" "${2:-$INSTALL_DIR/.env}" | tail -1; }

# Writes KEY=VALUE in an env file, replacing the line if it is there. Through
# ENVIRON, so no character in the value is ever taken as syntax.
env_set() {
  local file="$1" tmp
  tmp="$(mktemp "$file.XXXX")"
  K="$2" V="$3" awk '
    index($0, ENVIRON["K"] "=") == 1 { print ENVIRON["K"] "=" ENVIRON["V"]; done = 1; next }
    { print }
    END { if (!done) print ENVIRON["K"] "=" ENVIRON["V"] }
  ' "$file" >"$tmp"
  chmod --reference="$file" "$tmp"
  mv -f "$tmp" "$file"
}

release_value() { sed -n "s/^$1=//p" "$2" | tail -1; }

random_secret() { openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-"${1:-40}"; }

# The first name or address the plant reaches the system by.
first_site() { env_value PREDICTIVE_SITES | cut -d, -f1 | tr -d ' '; }

# Verifies a delivery against our public key before anything is unpacked or
# loaded: the signature is cosign's (ECDSA P-256 over SHA-256, base64), which
# openssl checks with no other tool on the server.
verify_delivery() {
  local tar="$1" pub="$2" der
  [[ -f "$tar" ]] || die "no existe el paquete $tar"
  [[ -f "$tar.sig" ]] || die "falta la firma $tar.sig junto al paquete"
  der="$(mktemp)"
  if base64 -d "$tar.sig" >"$der" 2>/dev/null \
    && openssl dgst -sha256 -verify "$pub" -signature "$der" "$tar" >/dev/null 2>&1; then
    rm -f "$der"
    return 0
  fi
  rm -f "$der"
  die "la firma no corresponde: este paquete no es de Industrie Ampel o fue alterado. No se carga."
}

load_images() {
  say "cargando las imágenes (unos minutos)…"
  gunzip -c "$1/images.tar.gz" | docker load -q >/dev/null
}

# HTTPS answers and the API behind it responds. Through the proxy, as the
# plant's browsers reach it; the certificate is checked elsewhere.
wait_serving() {
  local host code
  host="$(first_site)"
  for _ in $(seq 1 150); do
    code="$(curl -sk -o /dev/null -w '%{http_code}' --resolve "$host:443:127.0.0.1" \
      "https://$host/api/v1/license/status/" 2>/dev/null || true)"
    [[ "$code" == "200" ]] && return 0
    sleep 2
  done
  return 1
}

# Every step returns on failure by itself: update.sh calls this on the left of
# `||`, where bash ignores `set -e`, and a failed migration must reach the
# rollback instead of being followed by the next step.
migrate_all() {
  local tenant="$1" code pending
  manage migrate --database=default --verbosity 0 || return 1
  manage tenants migrate "$tenant" >/dev/null || return 1
  # New automatic modules, and the new version of those already installed.
  manage tenants run "$tenant" modules bootstrap >/dev/null || return 1
  pending="$(manage tenants run "$tenant" modules list)" || return 1
  for code in $(awk '$1 == "↑" {print $2}' <<<"$pending"); do
    manage tenants run "$tenant" modules upgrade "$code" >/dev/null || return 1
  done
}

# The customer database is registered in the control plane with its URL; a
# restored control plane carries the old server's password, so it is pointed
# at this one again.
point_tenant() {
  local tenant name password
  tenant="$(env_value TENANT)"
  name="$(env_value CUSTOMER_NAME)"
  password="$(env_value PREDICTIVE_DB_PASSWORD)"
  manage tenants add "$tenant" "$name" --deployment on_premise \
    --url "postgres://predictive_app:$password@db:5432/predictive_$tenant" >/dev/null
}

restore_databases() {
  local dir="$1" tenant db
  tenant="$(env_value TENANT)"
  dc up -d --wait db >/dev/null || return 1
  for db in predictive_control "predictive_$tenant"; do
    dc exec -T -u postgres db psql -q -v ON_ERROR_STOP=1 \
      -c "drop database if exists \"$db\" with (force)" \
      -c "create database \"$db\" owner predictive_app" >/dev/null || return 1
  done
  dc exec -T -u postgres db pg_restore --exit-on-error --no-owner --no-acl --role=predictive_app \
    -d predictive_control <"$dir/control.dump" || return 1
  dc exec -T -u postgres db pg_restore --exit-on-error --no-owner --no-acl --role=predictive_app \
    -d "predictive_$tenant" <"$dir/tenant.dump"
}

restore_data() {
  dc run --rm --no-deps -T --entrypoint sh api -c \
    'find /app/data -mindepth 1 -delete && tar -xzf - -C /app/data' <"$1/data.tar.gz"
}

check_backup() {
  local dir="$1"
  [[ -f "$dir/SHA256SUMS" ]] || die "$dir no es un respaldo de PREDICTIVE (falta SHA256SUMS)"
  (cd "$dir" && sha256sum --quiet -c SHA256SUMS) || die "el respaldo $dir está incompleto o alterado"
}

# What the licence allows right now, in the customer's words.
licence_status() {
  manage shell --verbosity 0 -c "
from modules.licensing.application.license_service import current_verdict
from modules.licensing.infrastructure.keys import trusted_keys
verdict = current_verdict('$(env_value TENANT)', keys=trusted_keys())
print('estado:', verdict.status.value)
print('días de licencia:', verdict.days_left)
print(verdict.reason or 'todo habilitado: registrar, consultar, exportar e informes')
"
}

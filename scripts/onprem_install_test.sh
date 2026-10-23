#!/usr/bin/env bash
# The installer on clean servers with no internet (predictive-docs docs/v4,
# Phase 6). Real virtual machines (KVM), Ubuntu Server 24.04 with Docker from
# Ubuntu's own archive, as the customer's IT would leave them; the deliveries
# are signed with the bench's throwaway keys, never ours.
#
#   scripts/onprem_install_test.sh golden    the clean server, once (needs internet)
#   scripts/onprem_install_test.sh bundles   three test deliveries: 1.0.0, 1.0.1, and
#                                            1.0.2 whose migration fails (REBUILD=1
#                                            recompiles images that already exist)
#   scripts/onprem_install_test.sh run       the acceptance checks, on new VMs, offline
#   scripts/onprem_install_test.sh clean     destroy the test VMs (keeps golden and bundles)
#
# The VMs live on a libvirt network with no route and no DNS out: every check
# runs with the server cut off from the internet (AC-6.4). The host reaches
# them over that network, the way a USB stick and a browser in the plant would.
#
# No pipefail: `… | grep -q` ends its writer early, and pipefail would turn a
# match into a failure.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Its own state and keys, apart from the bench's: `onprem_test.sh reset` wipes
# .onprem-test, and once wiped a run in progress here with it.
STATE="$ROOT/.onprem-vm"
KEYS="$STATE/keys"
# libvirt's qemu user cannot enter a home directory; disks live where it can.
VMDIR="${ONPREM_VM_DIR:-/var/tmp/predictive-vm}"
BASE_IMAGE="$VMDIR/noble-server-cloudimg-amd64.img"
GOLDEN="$VMDIR/golden.qcow2"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
VIRSH=(virsh -q -c qemu:///system)
NET=predictive-iso
TENANT=ipsa
V1=1.0.0-banco V2=1.0.1-banco V3=1.0.2-banco
SITE=predictive.ipsa.test
SSH_KEY="$STATE/ssh/id_ed25519"
SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR
  -o ConnectTimeout=5)
BOOKS="${ONPREM_BOOKS:-$ROOT/../predictive-docs/docs/v3/EQUIPOS PLANTA IPSA - SEPTIEMBRE}"

failed=0
pass() { echo "  ✓ $1"; }
fail() { echo "  ✗ $1"; failed=1; }
die() { echo "ERROR: $1" >&2; exit 1; }

# ------------------------------------------------------------------ machines

seed() {
  # name, extra user-data lines
  local name="$1" dir="$STATE/seed-$1"
  mkdir -p "$dir"
  cat >"$dir/meta-data" <<EOF
instance-id: $name-$(date +%s)
local-hostname: $name
EOF
  cat >"$dir/user-data" <<EOF
#cloud-config
hostname: $name
users:
  - name: ti
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys: [$(cat "$SSH_KEY.pub")]
${2:-}
EOF
  echo "$dir"
}

vm_ip() {
  local mac
  mac="$("${VIRSH[@]}" domiflist "$1" | awk 'NR>0 {print $5}' | head -1)"
  for _ in $(seq 1 120); do
    ip="$("${VIRSH[@]}" net-dhcp-leases "$2" 2>/dev/null | awk -v m="$mac" '$3 == m {print $5}' | cut -d/ -f1 | tail -1)"
    [[ -n "$ip" ]] && { echo "$ip"; return 0; }
    sleep 2
  done
  return 1
}

on() { local ip="$1"; shift; ssh "${SSH_OPTS[@]}" "ti@$ip" "$@"; }
copy_to() { local ip="$1"; shift; scp -q "${SSH_OPTS[@]}" "$@" "ti@$ip:" ; }

wait_ssh() {
  for _ in $(seq 1 120); do
    on "$1" true 2>/dev/null && return 0
    sleep 2
  done
  return 1
}

network() {
  "${VIRSH[@]}" net-info "$NET" >/dev/null 2>&1 && return
  cat >"$STATE/net.xml" <<EOF
<network>
  <name>$NET</name>
  <bridge name="virbr-pred" stp="on" delay="0"/>
  <dns enable="no"/>
  <ip address="192.168.150.1" netmask="255.255.255.0">
    <dhcp><range start="192.168.150.10" end="192.168.150.99"/></dhcp>
  </ip>
</network>
EOF
  "${VIRSH[@]}" net-define "$STATE/net.xml" >/dev/null
  "${VIRSH[@]}" net-start "$NET" >/dev/null
}

golden() {
  mkdir -p "$STATE/ssh"
  [[ -f "$SSH_KEY" ]] || ssh-keygen -q -t ed25519 -N "" -f "$SSH_KEY"
  [[ -f "$BASE_IMAGE" ]] || die "falta $BASE_IMAGE (Ubuntu 24.04 cloud image)"
  # The test VMs' disks sit on top of this one.
  clean
  "${VIRSH[@]}" destroy predictive-golden >/dev/null 2>&1
  "${VIRSH[@]}" undefine predictive-golden >/dev/null 2>&1
  rm -f "$GOLDEN"
  # 420 GB, thin: the installer checks for the 400 GB the proposal asks.
  qemu-img create -q -f qcow2 -b "$BASE_IMAGE" -F qcow2 "$GOLDEN" 420G
  local dir ip
  dir="$(seed predictive-golden "package_update: true
packages: [docker.io, docker-compose-v2]
runcmd:
  - [systemctl, enable, --now, docker]")"
  virt-install --connect qemu:///system --name predictive-golden --memory 4096 --vcpus 4 \
    --disk "path=$GOLDEN,format=qcow2,bus=virtio" --network network=default,model=virtio \
    --osinfo detect=on,require=off --import --graphics none --noautoconsole \
    --cloud-init "user-data=$dir/user-data,meta-data=$dir/meta-data" >/dev/null || die "virt-install falló"
  ip="$(vm_ip predictive-golden default)" || die "la VM base no tomó IP"
  wait_ssh "$ip" || die "la VM base no abrió SSH"
  on "$ip" "cloud-init status --wait >/dev/null; docker compose version" || die "Docker no quedó instalado"
  # Each VM made from this disk is a new machine: a new machine id, and
  # cloud-init runs again for it.
  on "$ip" "sudo cloud-init clean --logs --machine-id && sudo shutdown -h now" 2>/dev/null
  for _ in $(seq 1 60); do
    [[ "$("${VIRSH[@]}" domstate predictive-golden 2>/dev/null)" == "shut off" ]] && break
    sleep 2
  done
  "${VIRSH[@]}" undefine predictive-golden >/dev/null
  echo "servidor limpio listo: $GOLDEN"
}

# A new server from the clean one, on the network with no way out.
new_vm() {
  local name="$1" disk="$VMDIR/$1.qcow2" dir
  "${VIRSH[@]}" destroy "$name" >/dev/null 2>&1
  "${VIRSH[@]}" undefine "$name" >/dev/null 2>&1
  rm -f "$disk"
  qemu-img create -q -f qcow2 -b "$GOLDEN" -F qcow2 "$disk"
  dir="$(seed "$name")"
  virt-install --connect qemu:///system --name "$name" --memory 8192 --vcpus 4 \
    --disk "path=$disk,format=qcow2,bus=virtio" --network "network=$NET,model=virtio" \
    --osinfo detect=on,require=off --import --graphics none --noautoconsole \
    --cloud-init "user-data=$dir/user-data,meta-data=$dir/meta-data" >/dev/null || return 1
  vm_ip "$name" "$NET"
}

clean() {
  for name in predictive-a predictive-b; do
    "${VIRSH[@]}" destroy "$name" >/dev/null 2>&1
    "${VIRSH[@]}" undefine "$name" >/dev/null 2>&1
    rm -f "$VMDIR/$name.qcow2"
  done
}

# ------------------------------------------------------------------ deliveries

# Throwaway keys of these tests: one signs the licences and the integrity
# manifest (as ours does), the other the deliveries (as cosign's does).
test_keys() {
  mkdir -p "$KEYS"
  chmod 700 "$KEYS"
  if [[ ! -f "$KEYS/signing-key.pem" ]]; then
    (umask 077 && "$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(24))' >"$KEYS/password")
    issuer license keygen --signing-key "$KEYS/signing-key.pem" --password-file "$KEYS/password" \
      --public-key "$KEYS/public.key" >/dev/null || die "no se generó la clave de firma de prueba"
  fi
  if [[ ! -f "$KEYS/delivery.key" ]]; then
    (umask 077 && openssl ecparam -name prime256v1 -genkey -noout -out "$KEYS/delivery.key")
    openssl ec -in "$KEYS/delivery.key" -pubout -out "$KEYS/delivery.pub" 2>/dev/null
  fi
}

# The working tree, with the bench's public key in place of ours: the images
# and the licences of these tests never involve our signing key.
source_copy() {
  local dir="$1"
  rm -rf "$dir"
  mkdir -p "$dir"
  rsync -a --exclude .venv --exclude .onprem-test --exclude .onprem-vm --exclude data --exclude entregas \
    --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache --exclude .mypy_cache \
    "$ROOT/" "$dir/"
  "$PYTHON" - "$dir/modules/licensing/domain/signing_key.py" "$(cat "$KEYS/public.key")" <<'EOF'
import re, sys
path, key = sys.argv[1], sys.argv[2]
text = open(path).read()
open(path, "w").write(re.sub(r'PUBLIC_KEY = ".*"', f'PUBLIC_KEY = "{key}"', text))
EOF
}

# A migration of the core module, after its latest: one that applies, or one
# that fails halfway through an update.
add_migration() {
  local dir="$1" name="$2" body="$3" latest
  latest="$(cd "$dir/modules/core/migrations" && ls [0-9]*.py | sort | tail -1 | sed 's/\.py$//')"
  cat >"$dir/modules/core/migrations/$name.py" <<EOF
from django.db import migrations


$body


class Migration(migrations.Migration):
    dependencies = [("core", "$latest")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
EOF
}

bundles() {
  test_keys
  local out="$STATE/entregas" src
  mkdir -p "$out"
  for version in "$V1" "$V2" "$V3"; do
    src="$STATE/src-$version"
    source_copy "$src"
    if [[ "$version" != "$V1" ]]; then
      add_migration "$src" 9998_bench_update 'def forward(apps, schema_editor):
    pass'
    fi
    if [[ "$version" == "$V3" ]]; then
      add_migration "$src" 9999_bench_broken 'def forward(apps, schema_editor):
    raise RuntimeError("una migración de prueba que falla a mitad de la actualización")'
      sed -i 's/("core", "[^"]*")/("core", "9998_bench_update")/' "$src/modules/core/migrations/9999_bench_broken.py"
    fi
    # A script of the installation changes far more often than the program:
    # the sealed image is rebuilt only when asked (REBUILD=1) or missing.
    if [[ -n "${REBUILD:-}" ]] || ! docker image inspect "predictive:$TENANT-$version" >/dev/null 2>&1; then
      echo "construyendo $version…"
      COMPILE_LIMIT="${COMPILE_LIMIT:-6}" "$src/deploy/release/build.sh" "$TENANT" "$version" \
        "$KEYS/signing-key.pem" "$KEYS/password" >"$STATE/build-$version.log" 2>&1 \
        || die "no se construyó $version: ver $STATE/build-$version.log"
    fi
    FRONT="$ROOT/../predictive-front" DOCS="$ROOT/../predictive-docs" PYTHON="$PYTHON" \
      "$src/deploy/release/bundle.sh" "$TENANT" "$version" "$KEYS/delivery.key" "$KEYS/delivery.pub" "$out" \
      >>"$STATE/build-$version.log" 2>&1 || die "no se empaquetó $version: ver $STATE/build-$version.log"
    rm -rf "$src"
    echo "  $(ls -sh "$out/predictive-$TENANT-$version.tar" | cut -d' ' -f1) $out/predictive-$TENANT-$version.tar"
  done
}

# ------------------------------------------------------------------ licences

# Our issuing machine, played with the bench's key and a control plane of its own.
issuer() {
  (
    export DJANGO_SETTINGS_MODULE=config.settings.dev SECRET_KEY=onprem-vm-test
    export CONTROL_DATABASE_URL="sqlite:///$STATE/issuer.sqlite3" ALLOWED_HOSTS=localhost
    LICENSE_PUBLIC_KEY="$(cat "$KEYS/public.key" 2>/dev/null)"
    export LICENSE_PUBLIC_KEY
    cd "$ROOT" && "$PYTHON" manage.py "$@"
  )
}

licence_for() {
  # installation code, out file
  if [[ ! -f "$STATE/issuer.sqlite3" ]]; then
    issuer migrate --database=default --verbosity 0
    issuer tenants add "$TENANT" "IPSA" --url "sqlite:///$STATE/unused.sqlite3" --deployment on_premise >/dev/null
  fi
  # `--out` never overwrites a licence file, on purpose: last run's would be loaded.
  rm -f "$2"
  issuer tenants issue "$TENANT" --signing-key "$KEYS/signing-key.pem" --password-file "$KEYS/password" \
    --plan gestionado --grace 30 --equipment 650 --users 40 --plants 1 --months 3 \
    --installation "$1" --out "$2" >/dev/null || die "no se emitió la licencia para $1"
}

# ------------------------------------------------------------------ checks

# HTTPS from the plant: the host, trusting the installation's own authority.
https() {
  # ip, path, [curl args…]
  local ip="$1" path="$2"
  shift 2
  curl -s --cacert "$STATE/ca.crt" --resolve "$SITE:443:$ip" "$@" "https://$SITE$path"
}

field() { "$PYTHON" -c 'import json, sys
try: print(json.loads(sys.argv[1]).get(sys.argv[2], ""))
except ValueError: print("")' "$1" "$2"; }

login() {
  # ip, email, password → access token
  field "$(https "$1" /api/v1/auth/login/ -H 'Content-Type: application/json' \
    -d "{\"email\": \"$2\", \"password\": \"$3\"}")" access
}

psql_on() { on "$1" "cd /opt/predictive && sudo docker compose exec -T -u postgres db psql -tA -d predictive_$TENANT -c \"$2\""; }

counts() {
  psql_on "$1" "select (select count(*) from assets_assetgroup) || '/' || (select count(*) from assets_equipment)
    || '/' || (select count(*) from assets_measurementpoint) || '/' || (select count(*) from measurements_reading)
    || '/' || (select count(*) from media_mediaasset)"
}

offline_checks() {
  local ip="$1"
  if on "$ip" "curl -s -m 5 -o /dev/null https://1.1.1.1" 2>/dev/null \
    || on "$ip" "getent hosts cloud-images.ubuntu.com" >/dev/null 2>&1; then
    fail "el servidor $2 llega a internet: la prueba no sería sin conexión"
  else
    pass "el servidor $2 no tiene salida a internet (ni ruta ni DNS)"
  fi
}

run() {
  local a b out status started minutes admin token code here lic backup before after
  clean
  network
  [[ -f "$GOLDEN" ]] || die "falta el servidor limpio: $0 golden"
  for version in "$V1" "$V2" "$V3"; do
    [[ -f "$STATE/entregas/predictive-$TENANT-$version.tar" ]] || die "faltan las entregas: $0 bundles"
  done
  local entregas="$STATE/entregas"
  rm -f "$STATE/ca.crt"

  echo "Servidor A, limpio y sin internet"
  a="$(new_vm predictive-a)" || die "la VM A no arrancó"
  wait_ssh "$a" || die "la VM A no abrió SSH"
  on "$a" "cloud-init status --wait" >/dev/null 2>&1
  offline_checks "$a" A

  echo "Entrega firmada (lo que hace su TI antes de instalar)"
  copy_to "$a" "$entregas/predictive-$TENANT-$V1.tar" "$entregas/predictive-$TENANT-$V1.tar.sig" \
    "$entregas/predictive-entregas.pub"
  # The manual's command, verbatim.
  if on "$a" "base64 -d predictive-$TENANT-$V1.tar.sig > firma.der && openssl dgst -sha256 \
      -verify predictive-entregas.pub -signature firma.der predictive-$TENANT-$V1.tar" | grep -q "Verified OK"; then
    pass "la firma de la entrega verifica con openssl, sin cosign en el servidor"
  else
    fail "la firma de la entrega no verifica"
  fi
  if on "$a" "cp predictive-$TENANT-$V1.tar alterada.tar && printf X >> alterada.tar && openssl dgst -sha256 \
      -verify predictive-entregas.pub -signature firma.der alterada.tar; rm -f alterada.tar" | grep -q "Verified OK"; then
    fail "una entrega alterada verificó"
  else
    pass "una entrega alterada no verifica"
  fi

  echo "Instalación (AC-6.1)"
  cat >"$STATE/respuestas-a.conf" <<EOF
CUSTOMER_NAME=Industrias del Papel S.A.
CUSTOMER_TAX_ID=20100151546
PREDICTIVE_SITES=$SITE, $a
ADMIN_EMAIL=ti@ipsa.com.pe
ADMIN_PASSWORD=una-clave-de-prueba-2026
BACKUP_DIR=/srv/respaldos/predictive
BACKUP_KEEP_DAYS=30
MODULES=vibration thermography
EOF
  copy_to "$a" "$STATE/respuestas-a.conf"
  started=$SECONDS
  out="$(on "$a" "tar -xf predictive-$TENANT-$V1.tar && cd predictive-$TENANT-$V1 \
    && sudo ./install.sh --answers ../respuestas-a.conf" 2>&1)" && status=0 || status=$?
  minutes=$(((SECONDS - started + 59) / 60))
  echo "$out" >"$STATE/install-a.log"
  if [[ $status -eq 0 && $minutes -le 30 ]]; then
    pass "install.sh deja PREDICTIVE sirviendo en un servidor limpio, en $minutes min, sin pasos fuera del guion"
  else
    fail "install.sh falló o tardó (salida $status, $minutes min): $(tail -3 <<<"$out")"
    return 1
  fi
  on "$a" "sudo cat /opt/predictive/tls/predictive-ca.crt" >"$STATE/ca.crt" 2>/dev/null
  code="$(https "$a" / -o "$STATE/index.html" -w '%{http_code}')"
  [[ "$code" == "200" ]] && grep -q 'id="root"' "$STATE/index.html" \
    && pass "el front responde por HTTPS con el certificado de la autoridad de la instalación" \
    || fail "el front no responde por HTTPS con un certificado de confianza (HTTP ${code:-ninguno})"
  code="$(curl -s -o /dev/null -w '%{http_code}' --cacert "$STATE/ca.crt" "https://$a/api/v1/license/status/")"
  [[ "$code" == "200" ]] && pass "también por IP, con certificado válido para la IP" \
    || fail "por IP no responde con un certificado válido (HTTP ${code:-ninguno})"
  if curl -s -m 3 -o /dev/null "http://$a:8000/" || curl -s -m 3 -o /dev/null "http://$a:5432/"; then
    fail "la aplicación o la base responden fuera del proxy"
  else
    pass "la aplicación y la base no son alcanzables desde la red: solo el proxy"
  fi
  [[ "$(curl -s -o /dev/null -w '%{redirect_url}' "http://$a/")" == https://* ]] \
    && pass "HTTP redirige a HTTPS" || fail "HTTP no redirige a HTTPS"

  echo "Licencia en dos pasos (P6-c)"
  out="$(https "$a" /api/v1/license/status/)"
  [[ "$(field "$out" status)" == "invalid" && "$(field "$out" lapsed)" == "True" ]] \
    && pass "sin licencia todavía: consultar y exportar" || fail "sin licencia responde: $out"
  admin="$(login "$a" ti@ipsa.com.pe una-clave-de-prueba-2026)"
  [[ -n "$admin" ]] && pass "el primer administrador entra" || fail "el administrador no puede entrar"
  code="$(https "$a" /api/v1/users/me/language/ -o /dev/null -w '%{http_code}' -X PUT \
    -H "Authorization: Bearer $admin" -H 'Content-Type: application/json' -d '{"language": "es"}')"
  [[ "$code" == "402" ]] && pass "sin licencia no se registra (402)" || fail "sin licencia se pudo escribir (HTTP $code)"
  here="$(on "$a" "sudo sed -n 's/^instalación: //p' /opt/predictive/solicitud-licencia.txt")"
  if [[ "$here" =~ ^[0-9a-f-]{36}:[0-9a-f]{32}:[0-9a-f]{32}$ ]]; then
    pass "la solicitud de licencia queda guardada con el código de esta instalación"
  else
    fail "no quedó la solicitud de licencia: ${here:-vacía}"
  fi
  lic="$STATE/a.lic"
  licence_for "$here" "$lic"
  copy_to "$a" "$lic"
  out="$(on "$a" "sudo /opt/predictive/license.sh import a.lic" 2>&1)"
  echo "$out" >"$STATE/license-a.log"
  admin="$(login "$a" ti@ipsa.com.pe una-clave-de-prueba-2026)"
  code="$(https "$a" /api/v1/users/me/language/ -o /dev/null -w '%{http_code}' -X PUT \
    -H "Authorization: Bearer $admin" -H 'Content-Type: application/json' -d '{"language": "es"}')"
  [[ "$out" == *"estado: active"* && "$code" == "200" ]] \
    && pass "el .lic se carga con license.sh y el sistema registra" \
    || fail "cargar el .lic no activó el sistema (HTTP $code): ${out: -200}"

  echo "Su planta (los libros de IPSA, cargados en el servidor)"
  tar -C "$(dirname "$BOOKS")" -czf "$STATE/libros.tgz" "$(basename "$BOOKS")"
  copy_to "$a" "$STATE/libros.tgz"
  on "$a" "mkdir -p libros/docs/v3 && tar -xzf libros.tgz -C libros/docs/v3 && cd /opt/predictive \
    && sudo docker compose run --rm -T -v /home/ti/libros:/libros:ro api python manage.py \
      tenants run $TENANT import_ipsa --docs /libros --no-images" >"$STATE/import-a.log" 2>&1
  token="$(https "$a" /api/v1/service-visits/?page_size=1 -H "Authorization: Bearer $admin")"
  "$PYTHON" -c 'from PIL import Image; Image.new("RGB", (8, 8), (200, 30, 30)).save("'"$STATE"'/foto.png")'
  visit="$(psql_on "$a" "select min(id) from services_servicevisit")"
  https "$a" /api/v1/media/ -o /dev/null -H "Authorization: Bearer $admin" -F "file=@$STATE/foto.png" \
    -F kind=photo -F owner_type=visit -F "owner_id=$visit"
  before="$(counts "$a")"
  [[ "$before" == 47/98/795/10536/1 ]] \
    && pass "IPSA cargada con el importador: 47 conjuntos, 98 equipos, 795 puntos, 10 536 lecturas y una foto" \
    || fail "la carga de IPSA no dio los conteos esperados: $before"

  echo "Respaldo (AC-6.3)"
  out="$(on "$a" "sudo /opt/predictive/backup.sh" 2>&1)" && status=0 || status=$?
  backup="$(tail -1 <<<"$out" | cut -d' ' -f1)"
  if [[ $status -eq 0 ]] && on "$a" "sudo test -s $backup/control.dump -a -s $backup/tenant.dump -a -s $backup/data.tar.gz \
      && sudo sh -c 'cd $backup && sha256sum --quiet -c SHA256SUMS'"; then
    pass "backup.sh deja las dos bases y los archivos, con sus sumas"
  else
    fail "backup.sh no dejó un respaldo completo (salida $status): ${out: -200}"
  fi
  on "$a" "systemctl is-enabled predictive-nightly.timer && systemctl list-timers predictive-nightly.timer --no-legend" \
    | grep -q "predictive-nightly" && pass "el respaldo diario queda programado" \
    || fail "el respaldo diario no quedó programado"
  on "$a" "sudo mkdir -p /srv/respaldos/predictive/predictive-$TENANT-20200101-000000 \
    /srv/respaldos/predictive/predictive-$TENANT-20990101-000000 \
    && sudo touch -d '45 days ago' /srv/respaldos/predictive/predictive-$TENANT-20200101-000000 \
    && sudo systemctl start predictive-nightly.service"
  if ! on "$a" "sudo test -d /srv/respaldos/predictive/predictive-$TENANT-20200101-000000" 2>/dev/null \
    && on "$a" "sudo test -d /srv/respaldos/predictive/predictive-$TENANT-20990101-000000 -a -d $backup"; then
    pass "la retención borra lo vencido y guarda lo reciente (corrida del temporizador)"
  else
    fail "la retención no se aplicó como debía"
  fi

  echo "Actualización sin internet (AC-6.2)"
  copy_to "$a" "$entregas/predictive-$TENANT-$V2.tar" "$entregas/predictive-$TENANT-$V2.tar.sig"
  on "$a" "cp predictive-$TENANT-$V2.tar alterada.tar && cp predictive-$TENANT-$V2.tar.sig alterada.tar.sig \
    && printf X >> alterada.tar"
  out="$(on "$a" "sudo /opt/predictive/update.sh alterada.tar" 2>&1)" && status=0 || status=$?
  [[ $status -ne 0 && "$out" == *"firma no corresponde"* \
    && "$(on "$a" "sudo sed -n 's/^VERSION=//p' /opt/predictive/.env")" == "$V1" ]] \
    && pass "una actualización alterada se rechaza antes de tocar nada" \
    || fail "una actualización alterada no se rechazó (salida $status): ${out: -200}"
  on "$a" "rm -f alterada.tar alterada.tar.sig"
  out="$(on "$a" "sudo /opt/predictive/update.sh predictive-$TENANT-$V2.tar" 2>&1)" && status=0 || status=$?
  echo "$out" >"$STATE/update-v2.log"
  after="$(counts "$a")"
  if [[ $status -eq 0 && "$(on "$a" "sudo sed -n 's/^VERSION=//p' /opt/predictive/.env")" == "$V2" \
    && "$(psql_on "$a" "select count(*) from django_migrations where name = '9998_bench_update'")" == "1" \
    && "$after" == "$before" ]]; then
    pass "update.sh aplica $V2 con su migración, y los datos siguen ($after)"
  else
    fail "update.sh no aplicó $V2 (salida $status, datos $after): ${out: -300}"
  fi
  [[ "$(https "$a" /api/v1/license/status/ | grep -o '"status": *"[a-z_]*"')" == *active* ]] \
    && pass "tras actualizar, la licencia sigue vigente" || fail "tras actualizar la licencia cambió"

  copy_to "$a" "$entregas/predictive-$TENANT-$V3.tar" "$entregas/predictive-$TENANT-$V3.tar.sig"
  out="$(on "$a" "sudo /opt/predictive/update.sh predictive-$TENANT-$V3.tar" 2>&1)" && status=0 || status=$?
  echo "$out" >"$STATE/update-v3.log"
  after="$(counts "$a")"
  admin="$(login "$a" ti@ipsa.com.pe una-clave-de-prueba-2026)"
  if [[ $status -ne 0 && "$out" == *"revertida"* \
    && "$(on "$a" "sudo sed -n 's/^VERSION=//p' /opt/predictive/.env")" == "$V2" \
    && "$(psql_on "$a" "select count(*) from django_migrations where name = '9999_bench_broken'")" == "0" \
    && "$after" == "$before" && -n "$admin" ]]; then
    pass "una migración que falla vuelve a $V2 sola, sin perder datos, y sigue sirviendo"
  else
    fail "la migración fallida no volvió atrás limpia (salida $status, datos $after): ${out: -300}"
  fi
  [[ "$(on "$a" "sudo docker inspect -f '{{.Config.Image}}' predictive-api-1")" == "predictive:$TENANT-$V2" ]] \
    && pass "la API corre la imagen de $V2" || fail "la API no corre la imagen de $V2"

  out="$(on "$a" "sudo /opt/predictive/backup.sh" 2>&1)"
  backup="$(tail -1 <<<"$out" | cut -d' ' -f1)"
  rm -rf "$STATE/respaldo" && mkdir -p "$STATE/respaldo"
  on "$a" "sudo tar -C $(dirname "$backup") -cf - $(basename "$backup")" | tar -xf - -C "$STATE/respaldo"
  "${VIRSH[@]}" destroy predictive-a >/dev/null 2>&1

  echo "Servidor B: otra máquina, desde el respaldo (AC-6.3, P6-f)"
  b="$(new_vm predictive-b)" || die "la VM B no arrancó"
  wait_ssh "$b" || die "la VM B no abrió SSH"
  on "$b" "cloud-init status --wait" >/dev/null 2>&1
  offline_checks "$b" B
  sed "s/^PREDICTIVE_SITES=.*/PREDICTIVE_SITES=$SITE, $b/" "$STATE/respuestas-a.conf" >"$STATE/respuestas-b.conf"
  copy_to "$b" "$entregas/predictive-$TENANT-$V2.tar" "$STATE/respuestas-b.conf"
  (cd "$STATE/respaldo" && tar -cf - .) | on "$b" "mkdir -p respaldo && tar -xf - -C respaldo"
  out="$(on "$b" "tar -xf predictive-$TENANT-$V2.tar && cd predictive-$TENANT-$V2 \
    && sudo ./install.sh --answers ../respuestas-b.conf --restore /home/ti/respaldo/$(basename "$backup")" 2>&1)" \
    && status=0 || status=$?
  echo "$out" >"$STATE/install-b.log"
  on "$b" "sudo cat /opt/predictive/tls/predictive-ca.crt" >"$STATE/ca.crt" 2>/dev/null
  after="$(counts "$b")"
  [[ $status -eq 0 && "$after" == "$before" ]] \
    && pass "install.sh --restore reconstruye el sistema en otra máquina con todos sus datos ($after)" \
    || fail "la restauración en otra máquina falló (salida $status, datos $after): ${out: -300}"
  admin="$(login "$b" ti@ipsa.com.pe una-clave-de-prueba-2026)"
  token="$(psql_on "$b" "select original_key from media_mediaasset limit 1")"
  code="$(https "$b" "/media/$token" -o /dev/null -w '%{http_code}')"
  [[ -n "$admin" && "$code" == "200" ]] \
    && pass "la API arranca contra la base restaurada: entra el mismo usuario y la foto se sirve" \
    || fail "tras restaurar no entra el usuario o falta la foto (HTTP $code)"
  out="$(https "$b" /api/v1/license/status/)"
  code="$(https "$b" /api/v1/users/me/language/ -o /dev/null -w '%{http_code}' -X PUT \
    -H "Authorization: Bearer $admin" -H 'Content-Type: application/json' -d '{"language": "es"}')"
  [[ "$(field "$out" status)" == "other_installation" && "$code" == "402" ]] \
    && pass "en otra máquina la licencia queda en solo lectura hasta reactivarla (P6-f)" \
    || fail "en otra máquina la licencia responde $(field "$out" status) y escribir da $code"
  out="$(on "$b" "sudo /opt/predictive/license.sh request" 2>&1)"
  here="$(sed -n 's/^instalación: //p' <<<"$out")"
  licence_for "$here" "$STATE/b.lic"
  copy_to "$b" "$STATE/b.lic"
  out="$(on "$b" "sudo /opt/predictive/license.sh import b.lic" 2>&1)"
  echo "$out" >"$STATE/license-b.log"
  [[ "$out" == *"estado: active"* ]] \
    && pass "con la solicitud de siempre y su .lic, el servidor nuevo vuelve a registrar" \
    || fail "la reactivación en el servidor nuevo no funcionó: ${out: -200}"
  "${VIRSH[@]}" destroy predictive-b >/dev/null 2>&1

  return "$failed"
}

case "${1:-}" in
  golden) golden ;;
  bundles) bundles ;;
  run) run; status=$?; clean; exit "$status" ;;
  clean) clean ;;
  *) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

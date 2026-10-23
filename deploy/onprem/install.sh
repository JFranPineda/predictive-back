#!/usr/bin/env bash
# Installs PREDICTIVE on this server (v4 Phase 6).
#
#   sudo ./install.sh                                   asks for the customer's data
#   sudo ./install.sh --answers respuestas.conf         reads them from a file
#   sudo ./install.sh --answers r.conf --restore DIR    a new server from a backup
#
# Run from the folder of the extracted delivery, after verifying its signature
# (see the manual). Needs Docker with its compose plugin, and nothing from the
# internet: every image travels in the delivery.
#
# The first licence comes in two steps (P6-c): this leaves the request in
# /opt/predictive/solicitud-licencia.txt; Industrie Ampel answers with a .lic,
# loaded with `license.sh import`. Until then the system reads and exports.
set -euo pipefail
shopt -u patsub_replacement 2>/dev/null || true

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
STARTED=$SECONDS

ANSWERS="" RESTORE="" BELOW_MINIMUM=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --answers) ANSWERS="${2:?falta el archivo de respuestas}"; shift 2 ;;
    --restore) RESTORE="${2:?falta la carpeta del respaldo}"; shift 2 ;;
    # A lab or a test server below the minimum: warn instead of stopping.
    --below-minimum) BELOW_MINIMUM=1; shift ;;
    *) die "opción desconocida: $1" ;;
  esac
done

need_root
RELEASE="$HERE/VERSION"
[[ -f "$RELEASE" && -f "$HERE/images.tar.gz" ]] || die "corre install.sh desde la carpeta de la entrega"
[[ ! -f "$INSTALL_DIR/.env" ]] || die "PREDICTIVE ya está instalado en $INSTALL_DIR: una versión nueva se aplica con update.sh"
[[ -z "$RESTORE" ]] || check_backup "$RESTORE"

below() {
  if [[ $BELOW_MINIMUM -eq 1 ]]; then warn "$1"; else die "$1 (mínimo de la propuesta; ver «Requisitos» en el manual)"; fi
}

step "Requisitos"
command -v docker >/dev/null || die "falta Docker (ver «Requisitos» en el manual)"
docker compose version >/dev/null 2>&1 \
  || die "falta el plugin compose de Docker (paquete docker-compose-v2 o docker-compose-plugin)"
for tool in openssl curl base64 gunzip awk ss; do
  command -v "$tool" >/dev/null || die "falta $tool"
done
[[ -s /etc/machine-id ]] || die "/etc/machine-id está vacío: la licencia necesita la identidad de esta máquina"
cpus="$(nproc)"
mem_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
disk="$(df -B1 --output=size "$(docker info -f '{{.DockerRootDir}}')" | tail -1 | tr -d ' ')"
[[ $cpus -ge $MIN_CPUS ]] || below "$cpus vCPU, se necesitan $MIN_CPUS"
[[ $mem_kb -ge $MIN_MEM_KB ]] || below "$((mem_kb / 1024)) MB de memoria, se necesitan 8 GB"
[[ $disk -ge $MIN_DISK_BYTES ]] || below "disco de $((disk / 1000000000)) GB para Docker, se necesitan 400 GB"
if ss -ltnH '( sport = :443 or sport = :80 )' | grep -q .; then
  die "los puertos 80 o 443 ya están en uso en este servidor"
fi
say "$cpus vCPU · $((mem_kb / 1024 / 1024 + 1)) GB · $((disk / 1000000000)) GB de disco: bien"

step "Datos de la instalación"
answer() { [[ -n "$ANSWERS" ]] && sed -n "s/^$1=//p" "$ANSWERS" | tail -1; }
ask() {
  # VAR, question, default. From the answers file, or asked here.
  local value
  value="$(answer "$1" || true)"
  if [[ -z "$value" && -z "$ANSWERS" ]]; then
    read -r -p "$2${3:+ [$3]}: " value
  fi
  printf -v "$1" '%s' "${value:-${3:-}}"
}
TENANT="$(release_value TENANT "$RELEASE")"
VERSION="$(release_value VERSION "$RELEASE")"
ask CUSTOMER_NAME "Nombre de la empresa"
ask CUSTOMER_TAX_ID "RUC (opcional)"
ask PREDICTIVE_SITES "Nombres o IP por los que se entra (separados por coma)"
ask ADMIN_EMAIL "Correo del primer administrador"
ask ADMIN_PASSWORD "Su contraseña (vacío = se genera una)"
ask TLS_CERT "Certificado de su TI, ruta al .pem (vacío = autoridad propia)"
ask TLS_KEY "Su clave privada, ruta al .pem"
ask BACKUP_DIR "Carpeta del respaldo diario (un disco o su NAS montado)" "/srv/respaldos/predictive"
ask BACKUP_KEEP_DAYS "Días que se guarda cada respaldo" "30"
ask MODULES "Módulos contratados además de los automáticos (p. ej. vibration thermography)"

[[ -n "$CUSTOMER_NAME" && "$CUSTOMER_NAME" != *[\$\"\'\\]* ]] || die "falta el nombre de la empresa (sin comillas ni \$)"
[[ -n "$PREDICTIVE_SITES" ]] || die "falta al menos un nombre o IP del servidor"
[[ -n "$RESTORE" || "$ADMIN_EMAIL" == *@*.* ]] || die "el correo del administrador no es válido"
[[ "$BACKUP_KEEP_DAYS" =~ ^[0-9]+$ ]] || die "los días de respaldo deben ser un número"
if [[ -n "$TLS_CERT" || -n "$TLS_KEY" ]]; then
  [[ -f "$TLS_CERT" && -f "$TLS_KEY" ]] || die "el certificado o la clave de su TI no existen"
fi
GENERATED_PASSWORD=""
if [[ -z "$RESTORE" && -z "$ADMIN_PASSWORD" ]]; then
  ADMIN_PASSWORD="$(random_secret 16)"
  GENERATED_PASSWORD=1
fi
SITES="$(tr -d ' ' <<<"$PREDICTIVE_SITES" | sed 's/,/, /g')"
HOSTS="$(tr -d ' ' <<<"$PREDICTIVE_SITES")"
DEFAULT_SNI="$(tr ',' '\n' <<<"$HOSTS" | grep -m1 -E '^[0-9.]+$|^\[?[0-9a-fA-F:]+\]?$' || cut -d, -f1 <<<"$HOSTS")"

step "Imágenes"
load_images "$HERE"

step "Configuración en $INSTALL_DIR"
mkdir -p "$INSTALL_DIR/tls" "$INSTALL_DIR/initdb" "$BACKUP_DIR"
# The folder stays readable so `cd /opt/predictive` works for any admin; each
# secret is root's alone (.env, the TLS key, the licence request), and so are
# the backups, which carry all the data.
chmod 755 "$INSTALL_DIR"
chmod 700 "$BACKUP_DIR"
for file in compose.yml compose.online.yml lib.sh update.sh backup.sh restore.sh license.sh VERSION; do
  install -m "$([[ $file == *.sh ]] && echo 755 || echo 644)" "$HERE/$file" "$INSTALL_DIR/$file"
done
install -m 755 "$HERE/initdb/10-predictive.sh" "$INSTALL_DIR/initdb/"
install -m 644 "$HERE/delivery.pub" "$INSTALL_DIR/delivery.pub"
[[ -f "$HERE/manual-instalacion.pdf" ]] && install -m 644 "$HERE/manual-instalacion.pdf" "$INSTALL_DIR/"

declare -A VALUES=(
  [APP_IMAGE]="$(release_value APP_IMAGE "$RELEASE")" [WEB_IMAGE]="$(release_value WEB_IMAGE "$RELEASE")"
  [DB_IMAGE]="$(release_value DB_IMAGE "$RELEASE")" [REDIS_IMAGE]="$(release_value REDIS_IMAGE "$RELEASE")"
  [VERSION]="$VERSION" [TENANT]="$TENANT" [CUSTOMER_NAME]="$CUSTOMER_NAME"
  [PREDICTIVE_SITES]="$SITES" [PREDICTIVE_DEFAULT_SNI]="$DEFAULT_SNI" [ALLOWED_HOSTS]="$HOSTS"
  [BACKUP_DIR]="$BACKUP_DIR" [BACKUP_KEEP_DAYS]="$BACKUP_KEEP_DAYS"
  [POSTGRES_PASSWORD]="$(random_secret)" [PREDICTIVE_DB_PASSWORD]="$(random_secret)"
  [SECRET_KEY]="$(random_secret 60)"
)
content="$(cat "$HERE/env.example")"
for key in "${!VALUES[@]}"; do
  content="${content//"@$key@"/"${VALUES[$key]}"}"
done
[[ "$content" != *@[A-Z_]*@* ]] || die "quedó un valor sin completar en el .env"
(umask 077 && printf '%s\n' "$content" >"$INSTALL_DIR/.env")

# HTTPS (P6-d): their IT's certificate, or an authority of this installation.
if [[ -n "$TLS_CERT" ]]; then
  install -m 644 "$TLS_CERT" "$INSTALL_DIR/tls/cert.pem"
  install -m 600 "$TLS_KEY" "$INSTALL_DIR/tls/key.pem"
  echo "tls /etc/predictive/tls/cert.pem /etc/predictive/tls/key.pem" >"$INSTALL_DIR/tls/tls.caddy"
else
  echo "tls internal" >"$INSTALL_DIR/tls/tls.caddy"
fi

step "Base de datos"
dc up -d --wait db redis >/dev/null
if [[ -n "$RESTORE" ]]; then
  say "restaurando $RESTORE…"
  restore_databases "$RESTORE"
  restore_data "$RESTORE"
  point_tenant
  migrate_all "$TENANT"
else
  manage migrate --database=default --verbosity 0
  point_tenant
  manage tenants migrate "$TENANT" >/dev/null
  # The base catalogue before any module: their install hooks read it (P0-b).
  manage tenants run "$TENANT" catalog base --company "$TENANT" --name "$CUSTOMER_NAME" \
    --tax-id "$CUSTOMER_TAX_ID"
  manage tenants run "$TENANT" modules bootstrap
  for module in $MODULES; do
    manage tenants run "$TENANT" modules install "$module"
  done
  printf '%s' "$ADMIN_PASSWORD" | manage tenants run "$TENANT" catalog admin \
    --email "$ADMIN_EMAIL" --password-file -
fi

step "Arranque"
dc up -d >/dev/null
wait_serving || die "PREDICTIVE no responde por HTTPS: revisa 'docker compose logs' en $INSTALL_DIR"
if [[ -z "$TLS_CERT" ]]; then
  # The root the plant's PCs trust, so the browser shows no warning.
  for _ in $(seq 1 30); do
    dc cp web:/data/caddy/pki/authorities/local/root.crt "$INSTALL_DIR/tls/predictive-ca.crt" >/dev/null 2>&1 && break
    sleep 1
  done
  [[ -f "$INSTALL_DIR/tls/predictive-ca.crt" ]] || die "no se pudo leer la autoridad de la instalación"
fi

step "Respaldo diario"
cat >/etc/systemd/system/predictive-nightly.service <<EOF
[Unit]
Description=PREDICTIVE: archivo de registros y respaldo diario
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
Environment=PREDICTIVE_DIR=$INSTALL_DIR
ExecStart=$INSTALL_DIR/backup.sh --nightly
EOF
cat >/etc/systemd/system/predictive-nightly.timer <<EOF
[Unit]
Description=PREDICTIVE: respaldo diario a las 02:30

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now predictive-nightly.timer >/dev/null 2>&1
say "cada día a las 02:30 en $BACKUP_DIR, $BACKUP_KEEP_DAYS días"

step "Licencia"
(umask 077 && manage license request --tenant "$TENANT" >"$INSTALL_DIR/solicitud-licencia.txt")
licence_status | sed 's/^/  /'

minutes=$(((SECONDS - STARTED + 59) / 60))
cat <<EOF

PREDICTIVE $VERSION instalado en $minutes min: https://$(first_site)/
EOF
if [[ -z "$RESTORE" ]]; then
  say "  administrador: $ADMIN_EMAIL"
  [[ -n "$GENERATED_PASSWORD" ]] && say "  contraseña generada (anótala ahora, no se vuelve a mostrar): $ADMIN_PASSWORD"
fi
[[ -z "$TLS_CERT" ]] && say "  autoridad HTTPS para los PC de la planta: $INSTALL_DIR/tls/predictive-ca.crt"
cat <<EOF

Siguiente paso: enviar a Industrie Ampel la solicitud de licencia
  $INSTALL_DIR/solicitud-licencia.txt
y cargar el .lic que responda:
  sudo $INSTALL_DIR/license.sh import <archivo.lic>
Hasta entonces se puede entrar, consultar y exportar, pero no registrar.
EOF

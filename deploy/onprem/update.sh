#!/usr/bin/env bash
# Applies a new version of PREDICTIVE with no internet (v4 Phase 6).
#
#   sudo /opt/predictive/update.sh /ruta/predictive-ipsa-1.1.0.tar
#
# Verifies the delivery's signature with the key this installation already
# trusts, backs everything up, migrates and starts the new version. If a
# migration or the start fails, it goes back to the version that was running,
# with the data as it was before the update: the system is stopped meanwhile,
# so nothing is written between the backup and the way back.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

TAR="${1:?uso: update.sh <predictive-cliente-versión.tar>}"
need_root
TAR="$(cd "$(dirname "$TAR")" && pwd)/$(basename "$TAR")"
TENANT="$(env_value TENANT)"
CURRENT="$(env_value VERSION)"

step "Firma"
# The key installed with the first delivery, never one that comes in the new one.
verify_delivery "$TAR" "$INSTALL_DIR/delivery.pub"
say "la entrega es de Industrie Ampel y está íntegra"

step "Contenido"
RELEASES="$INSTALL_DIR/releases"
mkdir -p "$RELEASES"
# Unpacked into a folder of its own and named from what came out: `tar -t |
# head` would end tar with SIGPIPE, which pipefail turns into a failure.
UNPACKED="$(mktemp -d "$RELEASES/.unpacked.XXXX")"
tar -xf "$TAR" -C "$UNPACKED"
NAME="$(ls "$UNPACKED")"
[[ -f "$UNPACKED/$NAME/VERSION" ]] || die "el paquete no trae una entrega de PREDICTIVE"
rm -rf "${RELEASES:?}/$NAME"
mv "$UNPACKED/$NAME" "$RELEASES/$NAME"
rmdir "$UNPACKED"
NEW="$RELEASES/$NAME"
RELEASE="$NEW/VERSION"
[[ "$(release_value TENANT "$RELEASE")" == "$TENANT" ]] \
  || die "esta entrega es para otro cliente ($(release_value TENANT "$RELEASE")), no para $TENANT"
VERSION="$(release_value VERSION "$RELEASE")"
[[ "$VERSION" != "$CURRENT" ]] || die "la versión $VERSION ya está instalada"
say "$CURRENT → $VERSION"
load_images "$NEW"

step "Respaldo previo"
BACKUP="$("$INSTALL_DIR/backup.sh" --label "antes-de-$VERSION" | tail -1 | cut -d' ' -f1)"
check_backup "$BACKUP"
say "$BACKUP"

# What runs now, to go back to.
PREVIOUS="$INSTALL_DIR/previous"
rm -rf "$PREVIOUS"
mkdir -p "$PREVIOUS"
SHIPPED=(compose.yml compose.online.yml lib.sh update.sh backup.sh restore.sh license.sh VERSION)
cp -p "$INSTALL_DIR/.env" "$PREVIOUS/"
for file in "${SHIPPED[@]}"; do cp -p "$INSTALL_DIR/$file" "$PREVIOUS/"; done
cp -pr "$INSTALL_DIR/initdb" "$PREVIOUS/"

# A script is replaced by a new file, never rewritten in place: bash is still
# reading this one.
put() { cp -p "$1" "$INSTALL_DIR/.$2.new" && mv -f "$INSTALL_DIR/.$2.new" "$INSTALL_DIR/$2"; }

rollback() {
  set +e
  warn "$1"
  step "Volviendo a $CURRENT"
  dc stop web api worker beat >/dev/null 2>&1
  put "$PREVIOUS/.env" .env
  for file in "${SHIPPED[@]}"; do put "$PREVIOUS/$file" "$file"; done
  cp -pr "$PREVIOUS/initdb" "$INSTALL_DIR/"
  restore_databases "$BACKUP" && restore_data "$BACKUP" && dc up -d >/dev/null && wait_serving
  if [[ $? -eq 0 ]]; then
    die "actualización revertida: sigue corriendo $CURRENT con los datos de antes. Envía a Industrie Ampel la salida de arriba."
  fi
  die "no se pudo volver a $CURRENT. El respaldo previo está en $BACKUP: restore.sh $BACKUP"
}

step "Actualizando a $VERSION"
dc stop web api worker beat >/dev/null
for file in "${SHIPPED[@]}"; do put "$NEW/$file" "$file"; done
cp -p "$NEW/initdb/"* "$INSTALL_DIR/initdb/"
install -m 644 "$NEW/delivery.pub" "$INSTALL_DIR/delivery.pub"
[[ -f "$NEW/manual-instalacion.pdf" ]] && install -m 644 "$NEW/manual-instalacion.pdf" "$INSTALL_DIR/"
for key in APP_IMAGE WEB_IMAGE DB_IMAGE REDIS_IMAGE VERSION; do
  env_set "$INSTALL_DIR/.env" "$key" "$(release_value "$key" "$RELEASE")"
done

dc up -d --wait db redis >/dev/null || rollback "la base de datos de $VERSION no arrancó"
migrate_all "$TENANT" || rollback "las migraciones de $VERSION fallaron"
dc up -d >/dev/null || rollback "$VERSION no arrancó"
wait_serving || rollback "$VERSION no responde por HTTPS"

step "Limpieza"
# Keeps this version and the one before it, for a manual way back.
keep="$(env_value APP_IMAGE) $(env_value WEB_IMAGE) $(env_value APP_IMAGE "$PREVIOUS/.env") $(env_value WEB_IMAGE "$PREVIOUS/.env")"
for image in $(docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -E '^predictive(-web)?:'); do
  [[ " $keep " == *" $image "* ]] || docker image rm "$image" >/dev/null 2>&1 || true
done
find "$RELEASES" -mindepth 1 -maxdepth 1 -type d ! -name "$NAME" -exec rm -rf {} +
licence_status | sed 's/^/  /'
say "PREDICTIVE $VERSION en marcha (antes $CURRENT). Respaldo previo: $BACKUP"

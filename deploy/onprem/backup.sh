#!/usr/bin/env bash
# PREDICTIVE's backup (v4 Phase 6): both databases and the data volume (photos,
# thermograms, history), into the folder the customer chose in their network
# (P6-b), with retention.
#
#   sudo /opt/predictive/backup.sh                    a backup now
#   sudo /opt/predictive/backup.sh --label antes-de-1.1.0
#   /opt/predictive/backup.sh --nightly               the daily timer's run
#
# A backup is a folder: control.dump and tenant.dump (pg_dump), data.tar.gz,
# MANIFEST and SHA256SUMS. It carries no secret of this server's .env, so it
# restores onto a fresh installation (restore.sh). Exports are left out: each
# is a copy of everything, made again on demand.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

LABEL="" NIGHTLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) LABEL="${2:?falta la etiqueta}"; shift 2 ;;
    --nightly) NIGHTLY=1; shift ;;
    *) die "opción desconocida: $1" ;;
  esac
done
need_root

TENANT="$(env_value TENANT)"
DEST="$(env_value BACKUP_DIR)"
KEEP="$(env_value BACKUP_KEEP_DAYS)"
NAME="predictive-$TENANT-$(date +%Y%m%d-%H%M%S)${LABEL:+-$LABEL}"
mkdir -p "$DEST"

if [[ $NIGHTLY -eq 1 ]]; then
  # The logs older than the screens' fortnight go to their monthly CSV first,
  # so the backup carries them (doc 07 §3.bis).
  dc exec -T api python manage.py tenants run "$TENANT" history archive >/dev/null \
    || warn "no se pudo archivar el historial; el respaldo sigue"
fi

WORK="$DEST/.$NAME.partial"
rm -rf "$WORK"
mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT
dc exec -T -u postgres db pg_dump -Fc predictive_control >"$WORK/control.dump"
dc exec -T -u postgres db pg_dump -Fc "predictive_$TENANT" >"$WORK/tenant.dump"
dc run --rm --no-deps -T --entrypoint tar api -czf - -C /app/data --exclude=./exports . >"$WORK/data.tar.gz"
cat >"$WORK/MANIFEST" <<EOF
cliente=$TENANT
version=$(env_value VERSION)
imagen=$(env_value APP_IMAGE)
creado=$(date -Iseconds)
EOF
(cd "$WORK" && sha256sum control.dump tenant.dump data.tar.gz MANIFEST >SHA256SUMS)
chmod -R go-rwx "$WORK"
# Complete or absent: a backup cut short never looks like one.
mv "$WORK" "$DEST/$NAME"
trap - EXIT

# Retention: never the backup just made, whatever the clock says.
find "$DEST" -mindepth 1 -maxdepth 1 -type d -name "predictive-$TENANT-*" -mtime "+$KEEP" \
  ! -name "$NAME" -exec rm -rf {} +
say "$DEST/$NAME ($(du -sh "$DEST/$NAME" | cut -f1))"

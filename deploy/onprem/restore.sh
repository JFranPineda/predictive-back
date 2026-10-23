#!/usr/bin/env bash
# Restores a PREDICTIVE backup onto this installation (v4 Phase 6).
#
#   sudo /opt/predictive/restore.sh /srv/respaldos/predictive/predictive-ipsa-20261023-023000
#
# Replaces both databases and the data volume with the backup's, then brings
# the schema up to this version. On a different server the licence reads
# and exports at once, and registers again once a licence for this server is
# loaded (P6-f): `license.sh request`, then `license.sh import`.
# A new server is installed from the backup in one go: install.sh --restore.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

DIR="${1:?uso: restore.sh <carpeta del respaldo> [--yes]}"
need_root
check_backup "$DIR"
TENANT="$(env_value TENANT)"
[[ "$(sed -n 's/^cliente=//p' "$DIR/MANIFEST")" == "$TENANT" ]] \
  || die "el respaldo es de otro cliente, no de $TENANT"
if [[ "${2:-}" != "--yes" ]]; then
  read -r -p "Esto reemplaza TODOS los datos actuales por los del respaldo. ¿Seguir? (escribe SI): " ok
  [[ "$ok" == "SI" ]] || die "cancelado: no se tocó nada"
fi

step "Restaurando $DIR"
dc stop web api worker beat >/dev/null 2>&1 || true
restore_databases "$DIR"
restore_data "$DIR"
point_tenant
migrate_all "$TENANT"
dc up -d >/dev/null
wait_serving || die "PREDICTIVE no responde tras restaurar: revisa 'docker compose logs' en $INSTALL_DIR"
licence_status | sed 's/^/  /'
say "restaurado"

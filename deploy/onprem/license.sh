#!/usr/bin/env bash
# The installation's licence, from the server (v4 Phase 6).
#
#   sudo /opt/predictive/license.sh request            what to send to Industrie Ampel
#   sudo /opt/predictive/license.sh import archivo.lic load the licence it sends back
#   sudo /opt/predictive/license.sh status             what the licence allows now
#
# The request says exactly what leaves the network: the customer, the licence
# in force, this installation's code, the version and two counts (Phase 3).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

need_root
TENANT="$(env_value TENANT)"
case "${1:-}" in
  request)
    (umask 077 && manage license request --tenant "$TENANT" | tee "$INSTALL_DIR/solicitud-licencia.txt")
    say ""
    say "guardada en $INSTALL_DIR/solicitud-licencia.txt"
    ;;
  import)
    file="${2:?uso: license.sh import <archivo.lic>}"
    [[ -f "$file" ]] || die "no existe $file"
    manage license import /dev/stdin --tenant "$TENANT" <"$file"
    licence_status
    ;;
  status) licence_status ;;
  *) sed -n '4,6p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

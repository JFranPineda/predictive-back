#!/usr/bin/env bash
# At the customer: verify the signature before loading, and never run an image
# that is not ours or was altered (AC-5.4).
#
#   verify-and-run.sh <image.tar> <cosign.pub> [docker-run args…]
set -euo pipefail
TAR="${1:?uso: verify-and-run.sh <image.tar> <cosign.pub> [args…]}"
COSIGN_PUB="${2:?falta la clave pública cosign}"
shift 2
if ! cosign verify-blob --key "$COSIGN_PUB" --signature "$TAR.sig" "$TAR"; then
  echo "La firma no corresponde: no se carga esta imagen." >&2
  exit 1
fi
IMAGE="$(docker load -i "$TAR" | sed -n 's/^Loaded image: //p' | head -1)"
echo "imagen verificada y cargada: $IMAGE"
[[ "$#" -gt 0 ]] && exec docker run "$@" "$IMAGE"

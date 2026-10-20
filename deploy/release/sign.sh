#!/usr/bin/env bash
# Package a sealed image as a signed .tar for a customer with no internet
# (decision P5-b): docker save + a cosign signature over the archive.
#
#   sign.sh <image> <cosign.key> [out-dir]
set -euo pipefail
IMAGE="${1:?uso: sign.sh <image> <cosign.key> [out-dir]}"
COSIGN_KEY="${2:?falta la clave cosign}"
OUT="${3:-.}"
NAME="$(echo "$IMAGE" | tr '/:' '--')"
TAR="$OUT/${NAME}.tar"
mkdir -p "$OUT"
docker save "$IMAGE" -o "$TAR"
cosign sign-blob --yes --key "$COSIGN_KEY" --output-signature "$TAR.sig" "$TAR"
echo "$TAR"
echo "$TAR.sig"

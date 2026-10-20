#!/usr/bin/env bash
# Build a sealed, stamped image for one customer (v4 Phase 5).
#
#   build.sh <tenant> <version> [signing-key.pem] [password-file]
#
# The signing key signs the integrity manifest inside the build and never
# lands in a layer (BuildKit secret). COMPILE_LIMIT caps the native compiles
# for a quick build; unset compiles all the value to native, as a delivery.
# TARGET=verify builds the same image plus its tests (never delivered).
set -euo pipefail

TENANT="${1:?uso: build.sh <tenant> <version> [clave.pem] [password-file]}"
VERSION="${2:?falta la versión, p. ej. 1.0.0}"
KEY="${3:-$HOME/.config/predictive/licensing/signing-key.pem}"
PW="${4:-$HOME/predictive-signing-password.txt}"
BUILD_ID="$(date -u +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
TARGET="${TARGET:-runtime}"
IMAGE="predictive:${TENANT}-${VERSION}"
[[ "$TARGET" == "runtime" ]] || IMAGE="${IMAGE}-${TARGET}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

[[ -f "$KEY" && -f "$PW" ]] || { echo "falta la clave de firma ($KEY) o su contraseña ($PW)" >&2; exit 1; }
cd "$ROOT"
DOCKER_BUILDKIT=1 docker build -f deploy/release/Dockerfile --target "$TARGET" -t "$IMAGE" \
  --build-arg "BUILD_TENANT=$TENANT" --build-arg "BUILD_VERSION=$VERSION" --build-arg "BUILD_ID=$BUILD_ID" \
  ${COMPILE_LIMIT:+--build-arg COMPILE_LIMIT="$COMPILE_LIMIT"} \
  --secret "id=signing_key,src=$KEY" --secret "id=signing_pw,src=$PW" .
echo "$IMAGE"

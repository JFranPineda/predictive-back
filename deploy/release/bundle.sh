#!/usr/bin/env bash
# One customer's delivery for one version (v4 Phase 6): everything the
# installation needs, with no internet, in one signed .tar.
#
#   bundle.sh <tenant> <version> <delivery-key> <delivery.pub> [out-dir]
#
# Expects the sealed image from build.sh (predictive:<tenant>-<version>). Adds
# the web image (Caddy and the built front), the pinned PostgreSQL and Redis
# images, the installation's scripts and the manual, and signs the .tar with
# cosign. A plain EC key (the bench's throwaway one) signs with openssl: the
# signature is the same, and the server checks either with openssl alone.
#
# The customer receives three files: the .tar, its .sig and the public key,
# whose fingerprint the manual prints so their IT can check it.
set -euo pipefail

TENANT="${1:?uso: bundle.sh <tenant> <version> <clave de entrega> <pública> [salida]}"
VERSION="${2:?falta la versión}"
KEY="${3:?falta la clave que firma la entrega}"
PUB="${4:?falta su clave pública}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$(mkdir -p "${5:-$ROOT/entregas}" && cd "${5:-$ROOT/entregas}" && pwd)"
FRONT="${FRONT:-$ROOT/../predictive-front}"
DOCS="${DOCS:-$ROOT/../predictive-docs}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
DB_IMAGE=postgres:16.14
REDIS_IMAGE=redis:7.4.11-alpine
APP_IMAGE="predictive:$TENANT-$VERSION"
WEB_IMAGE="predictive-web:$TENANT-$VERSION"
NAME="predictive-$TENANT-$VERSION"

docker image inspect "$APP_IMAGE" >/dev/null 2>&1 || { echo "falta la imagen $APP_IMAGE (build.sh)" >&2; exit 1; }
BUILD_ID="$(docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$APP_IMAGE" | sed -n 's/^BUILD_ID=//p')"

echo "front…" >&2
(cd "$FRONT" && npm run build) >"$OUT/.front-build.log" 2>&1 \
  || { echo "el front no compiló: ver $OUT/.front-build.log" >&2; exit 1; }
[[ -z "$(find "$FRONT/dist" -name '*.map')" ]] || { echo "el front trae source maps" >&2; exit 1; }
docker build -q -f "$ROOT/deploy/release/web.Dockerfile" --build-context "front=$FRONT/dist" \
  --build-arg "BUILD_TENANT=$TENANT" --build-arg "BUILD_VERSION=$VERSION" --build-arg "BUILD_ID=$BUILD_ID" \
  -t "$WEB_IMAGE" "$ROOT" >/dev/null
for image in "$DB_IMAGE" "$REDIS_IMAGE"; do
  docker image inspect "$image" >/dev/null 2>&1 || docker pull -q "$image" >/dev/null
done

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME/initdb"
for file in compose.yml compose.online.yml env.example install.sh update.sh backup.sh restore.sh license.sh lib.sh; do
  cp -p "$ROOT/deploy/onprem/$file" "$STAGE/$NAME/"
done
cp -p "$ROOT/deploy/onprem/initdb/"*.sh "$STAGE/$NAME/initdb/"
cp "$PUB" "$STAGE/$NAME/delivery.pub"
cat >"$STAGE/$NAME/VERSION" <<EOF
TENANT=$TENANT
VERSION=$VERSION
BUILD_ID=$BUILD_ID
APP_IMAGE=$APP_IMAGE
WEB_IMAGE=$WEB_IMAGE
DB_IMAGE=$DB_IMAGE
REDIS_IMAGE=$REDIS_IMAGE
EOF
MANUAL="$DOCS/docs/v4/onprem-install-guide.md"
if [[ -f "$MANUAL" ]]; then
  "$PYTHON" "$ROOT/deploy/release/manual.py" "$MANUAL" "$STAGE/$NAME/manual-instalacion.pdf" \
    --version "$VERSION" --tenant "$TENANT" --delivery-key "$PUB"
else
  echo "sin $MANUAL: la entrega va sin manual" >&2
fi
echo "imágenes…" >&2
docker save "$APP_IMAGE" "$WEB_IMAGE" "$DB_IMAGE" "$REDIS_IMAGE" | gzip -1 >"$STAGE/$NAME/images.tar.gz"

TAR="$OUT/$NAME.tar"
tar -cf "$TAR" -C "$STAGE" "$NAME"
if head -1 "$KEY" | grep -q SIGSTORE; then
  # Asks for the key's password unless COSIGN_PASSWORD is set: the prompt must show.
  cosign sign-blob --yes --key "$KEY" --output-signature "$TAR.sig" "$TAR" >/dev/null
else
  openssl dgst -sha256 -sign "$KEY" "$TAR" | base64 -w0 >"$TAR.sig"
fi
cp "$PUB" "$OUT/predictive-entregas.pub"
echo "$TAR"

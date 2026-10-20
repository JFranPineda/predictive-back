#!/usr/bin/env bash
# The sealed-delivery checks (v4 Phase 5). Builds a stamped, signed image and
# proves the acceptance criteria against it. Our keys live outside the repo.
#
#   deploy/release/release_test.sh
#
# By default it builds exactly as a delivery: all the value compiled to native.
# COMPILE_LIMIT=14 caps the native compiles for a quicker run while iterating.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONT="$ROOT/../predictive-front"
TENANT=ipsa
VERSION=1.0.0-test
IMAGE="predictive:${TENANT}-${VERSION}"
KEY="${SIGNING_KEY:-$HOME/.config/predictive/licensing/signing-key.pem}"
PW="${SIGNING_PW:-$HOME/predictive-signing-password.txt}"
COSIGN_KEY="$HOME/.config/predictive/cosign/cosign.key"
COSIGN_PUB="$HOME/.config/predictive/cosign/cosign.pub"
COSIGN_PW_FILE="$HOME/.config/predictive/cosign/password"
WORK="$ROOT/.onprem-test/release"
export COMPILE_LIMIT="${COMPILE_LIMIT-}"
failed=0
pass() { echo "  ✓ $1"; }
fail() { echo "  ✗ $1"; failed=1; }
in_image() { docker run --rm -e SECRET_KEY=img -e ALLOWED_HOSTS=localhost "$IMAGE" "$@"; }
in_verify() { docker run --rm -e SECRET_KEY=img -e ALLOWED_HOSTS=localhost "$IMAGE-verify" "$@"; }

mkdir -p "$WORK"
echo "Construcción"
if COMPILE_LIMIT="$COMPILE_LIMIT" "$ROOT/deploy/release/build.sh" "$TENANT" "$VERSION" "$KEY" "$PW" >"$WORK/build.log" 2>&1; then
  pass "la imagen sellada se construye ($(docker images --format '{{.Size}}' "$IMAGE" | head -1))"
  if TARGET=verify COMPILE_LIMIT="$COMPILE_LIMIT" "$ROOT/deploy/release/build.sh" "$TENANT" "$VERSION" "$KEY" "$PW" \
    >>"$WORK/build.log" 2>&1; then
    pass "y su gemela de verificación (la misma imagen + pruebas, nunca se entrega)"
  else
    fail "la imagen de verificación no se construyó: $(tail -3 "$WORK/build.log")"
  fi
else
  fail "la imagen no se construyó: $(tail -3 "$WORK/build.log")"
  exit 1
fi

echo "Código cerrado (AC-5.1)"
# Nothing readable of ours anywhere in the delivery: not the product, not its
# tests (they spell out the rules), not the build tooling. Only Django's
# manage.py launcher remains.
leftover="$(in_image sh -c 'find /app -name "*.py" ! -path /app/manage.py | head')"
native="$(in_image sh -c 'find modules -name "*.so" | wc -l')"
[[ -z "$leftover" ]] && pass "ningún .py legible nuestro en la imagen de entrega (ni pruebas ni herramientas)" \
  || fail "quedaron .py en la imagen: $leftover"
[[ "$native" -gt 0 ]] && pass "el valor viaja como binarios nativos ($native .so)" \
  || fail "no hay módulos nativos en la imagen"
in_image cat /app/compile-report.json >"$WORK/compile-report.json" 2>/dev/null
fallbacks="$("$ROOT/.venv/bin/python" -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["fell_back_to_bytecode"]))' "$WORK/compile-report.json" 2>/dev/null || echo "?")"
[[ "$fallbacks" == "0" ]] && pass "Nuitka compiló todo el valor, sin caer a bytecode" \
  || fail "módulos que no compilaron a nativo: $fallbacks (ver $WORK/compile-report.json)"

out="$(docker run --rm -e SECRET_KEY=img -e ALLOWED_HOSTS=localhost -e DJANGO_SETTINGS_MODULE=config.settings.dev \
  "$IMAGE" python -c "import django; django.setup()" 2>&1)"
[[ "$out" == *"No module named 'config.settings.dev'"* ]] \
  && pass "la entrega no trae los ajustes de desarrollo: no hay por dónde saltar la licencia" \
  || fail "la entrega acepta los ajustes de desarrollo: ${out: -150}"

uid="$(docker run --rm --entrypoint id "$IMAGE" -u)"
[[ "$uid" != "0" ]] && pass "la entrega corre con un usuario sin privilegios (uid $uid)" \
  || fail "la entrega corre como root"

echo "Integridad al arranque (AC-5.6)"
if in_image python -c "import django; django.setup()" >"$WORK/setup.log" 2>&1; then
  pass "la imagen íntegra arranca (verifica su manifiesto firmado)"
else
  fail "la imagen íntegra no arrancó: $(tail -2 "$WORK/setup.log")"
fi
# As root: the customer's IT has root on its own server, and even then an
# altered file must not start.
out="$(docker run --rm --user root -e SECRET_KEY=img -e ALLOWED_HOSTS=localhost "$IMAGE" \
  sh -c 'f=$(find modules -name "*.pyc" | head -1); printf X >> "$f"; python -c "import django; django.setup()"' 2>&1)"
if [[ "$?" -ne 0 && "$out" == *"integridad"* ]]; then
  pass "un archivo alterado impide arrancar, y lo dice"
else
  fail "un archivo alterado no impidió arrancar: ${out: -200}"
fi

echo "La imagen sirve con su propio CMD (AC-5.2)"
cid="$(docker run -d -p 127.0.0.1:18000:8000 -e SECRET_KEY=img -e ALLOWED_HOSTS=127.0.0.1 "$IMAGE")"
code=""
for _ in $(seq 1 40); do
  code="$(curl -s -o "$WORK/serve.json" -w '%{http_code}' -H 'X-Forwarded-Proto: https' \
    http://127.0.0.1:18000/api/v1/license/status/ || true)"
  [[ "$code" != "000" && -n "$code" ]] && break
  sleep 0.5
done
docker logs "$cid" >"$WORK/serve.log" 2>&1; docker rm -f "$cid" >/dev/null
# No tenant on a bare image: the API's own 400 proves gunicorn → Django →
# middleware all run on the compiled program.
if [[ "$code" == "400" ]] && grep -q tenant_required "$WORK/serve.json"; then
  pass "arranca con su CMD (gunicorn) y responde la API compilada"
else
  fail "la imagen no sirve con su CMD (HTTP ${code:-ninguno}): $(tail -2 "$WORK/serve.log")"
fi

echo "Suite y dependencias nativas sobre la imagen (AC-5.2)"
if in_verify sh -c 'CONTROL_DATABASE_URL=sqlite:///tmp/c.sqlite3 python -m pytest -p no:cacheprovider' >"$WORK/pytest.log" 2>&1; then
  pass "pytest pasa sobre la imagen compilada ($(grep -oE '[0-9]+ passed' "$WORK/pytest.log" | tail -1))"
else
  fail "pytest falló sobre la imagen: $(tail -4 "$WORK/pytest.log")"
fi
if in_image python -c "import weasyprint, pillow_heif, numpy; weasyprint.HTML(string='<p>ok</p>').write_pdf(); print('ok')" \
  >"$WORK/native.log" 2>&1; then
  pass "weasyprint (PDF), pillow-heif (HEIC) y numpy funcionan en la imagen"
else
  fail "una dependencia nativa falló en la imagen: $(tail -2 "$WORK/native.log")"
fi

echo "Metadatos del PDF (AC-5.5)"
docker run --rm -i -e SECRET_KEY=img -e ALLOWED_HOSTS=localhost "$IMAGE" sh -c '
python - <<PYEOF
import django; django.setup()
from django.template.loader import render_to_string
from weasyprint import HTML
from modules.reports.infrastructure.render import _build_stamp
html = render_to_string("reports/base.html", {"title": "Informe", **_build_stamp()})
open("/tmp/r.pdf", "wb").write(HTML(string=html).write_pdf())
PYEOF
exiftool -Author -Creator /tmp/r.pdf' >"$WORK/pdfmeta.log" 2>&1
if grep -q "ipsa" "$WORK/pdfmeta.log" && grep -q "1.0.0-test" "$WORK/pdfmeta.log"; then
  pass "los PDF llevan cliente y versión en los metadatos ($(grep -i author "$WORK/pdfmeta.log" | head -1 | sed 's/  */ /g'))"
else
  fail "el PDF no lleva cliente/versión: $(cat "$WORK/pdfmeta.log")"
fi

echo "Front sin source maps (AC-5.3)"
if [[ -d "$FRONT" ]]; then
  (cd "$FRONT" && npm run build) >"$WORK/front.log" 2>&1
  maps="$(find "$FRONT/dist" -name '*.map' | wc -l)"
  [[ "$maps" == "0" ]] && pass "el front de producción no expone source maps" \
    || fail "el front expone $maps source maps"
else
  echo "  · sin $FRONT: no se comprueba el front"
fi

echo "Firma de la entrega (AC-5.4)"
tar="$WORK/${IMAGE//[\/:]/-}.tar"
docker save "$IMAGE" -o "$tar"
COSIGN_PASSWORD="$(cat "$COSIGN_PW_FILE")" cosign sign-blob --yes --key "$COSIGN_KEY" \
  --output-signature "$tar.sig" "$tar" >/dev/null 2>&1
if cosign verify-blob --key "$COSIGN_PUB" --signature "$tar.sig" "$tar" >/dev/null 2>&1; then
  pass "la entrega firmada verifica con nuestra clave pública"
else
  fail "la entrega firmada no verifica"
fi
printf X >> "$tar"
if cosign verify-blob --key "$COSIGN_PUB" --signature "$tar.sig" "$tar" >/dev/null 2>&1; then
  fail "una entrega alterada verificó (no debería)"
else
  pass "una entrega alterada no verifica: no se carga"
fi
rm -f "$tar" "$tar.sig"

exit "$failed"

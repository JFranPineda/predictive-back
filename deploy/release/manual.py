#!/usr/bin/env python
"""The installation manual as a PDF (v4 Phase 6, decision P6-a).

    manual.py <guide.md> <out.pdf> --version 1.0.0 --tenant ipsa --delivery-key cosign.pub

The guide is written once, in Markdown, in predictive-docs. The PDF carries
the version, the customer and the date, so it can go with the commissioning
record, and the fingerprint of the key that signs the deliveries, so their IT
can check the public key they were given is ours.
"""

from __future__ import annotations

import argparse
import hashlib
import html
from datetime import date
from pathlib import Path

import markdown
from cryptography.hazmat.primitives import serialization
from weasyprint import HTML

STYLE = """
@page { size: A4; margin: 22mm 20mm 20mm 20mm;
  @bottom-left { content: "PREDICTIVE · manual de instalación · %(version)s";
    font-family: "DejaVu Sans", sans-serif; font-size: 8pt; color: #64748b; }
  @bottom-right { content: counter(page) " / " counter(pages);
    font-family: "DejaVu Sans", sans-serif; font-size: 8pt; color: #64748b; } }
body { font-family: "DejaVu Sans", sans-serif; font-size: 10pt; line-height: 1.45; color: #0f172a; }
h1 { font-size: 20pt; margin: 0 0 4mm; }
h2 { font-size: 14pt; margin: 8mm 0 2mm; border-bottom: 1px solid #cbd5e1; padding-bottom: 1mm;
  break-after: avoid; }
h3 { font-size: 11pt; margin: 5mm 0 1mm; break-after: avoid; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 8.5pt; background: #f1f5f9; padding: 0 1mm; }
pre { background: #f1f5f9; padding: 3mm; border-radius: 2mm; white-space: pre-wrap; break-inside: avoid; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%%; margin: 2mm 0; break-inside: avoid; }
th, td { border: 1px solid #cbd5e1; padding: 1.5mm 2mm; text-align: left; vertical-align: top; }
th { background: #f1f5f9; }
.cover { border: 1px solid #cbd5e1; border-radius: 2mm; padding: 4mm; margin-bottom: 6mm; }
.cover p { margin: 1mm 0; }
"""


def fingerprint(public_key_pem: bytes) -> str:
    key = serialization.load_pem_public_key(public_key_pem)
    der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    digest = hashlib.sha256(der).hexdigest()
    return " ".join(digest[i:i + 4] for i in range(0, len(digest), 4))


def render(guide: Path, out: Path, *, version: str, tenant: str, delivery_key: Path) -> None:
    body = markdown.markdown(guide.read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])
    cover = (
        '<div class="cover">'
        f"<p><b>Versión:</b> {html.escape(version)} · <b>Cliente:</b> {html.escape(tenant)} · "
        f"<b>Fecha:</b> {date.today():%d/%m/%Y}</p>"
        "<p><b>Huella de la clave que firma las entregas</b> (comprobarla antes de instalar):<br>"
        f"<code>{fingerprint(delivery_key.read_bytes())}</code></p>"
        "</div>"
    )
    # The cover goes right under the guide's title.
    title_end = body.find("</h1>")
    if title_end >= 0:
        body = body[: title_end + 5] + cover + body[title_end + 5:]
    else:
        body = cover + body
    page = f"<html><head><meta charset='utf-8'><style>{STYLE % {'version': html.escape(version)}}</style>" \
           f"</head><body>{body}</body></html>"
    HTML(string=page).write_pdf(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("guide", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--delivery-key", type=Path, required=True)
    options = parser.parse_args()
    render(options.guide, options.out, version=options.version, tenant=options.tenant,
           delivery_key=options.delivery_key)


if __name__ == "__main__":
    main()

"""Asking our renewal service. The standard library only: one POST, a
timeout, and nothing but http(s)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from modules.licensing.application.renewal import RenewalUnavailableError
from modules.licensing.infrastructure.renewal_facts import program_version

TIMEOUT_SECONDS = 20
MAX_ANSWER_BYTES = 64_000


def post_json(url: str, payload: dict[str, Any]) -> object:
    # urllib also opens file:// and ftp://; a renewal URL is never one.
    if not url.startswith(("https://", "http://")):
        raise RenewalUnavailableError(f"la dirección de renovación no es http(s): {url}")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": f"PREDICTIVE/{program_version()}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read(MAX_ANSWER_BYTES))
    except urllib.error.HTTPError as exc:
        raise RenewalUnavailableError(f"el servicio respondió HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RenewalUnavailableError(f"no se pudo consultar el servicio: {exc}") from exc
    except ValueError as exc:
        raise RenewalUnavailableError("el servicio no respondió JSON") from exc

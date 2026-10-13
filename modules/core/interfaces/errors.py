"""What the API answers when a view fails on the input it was given.

Bad input must be a 4xx with a reason, never a 500: a 500 tells the person
"the system broke" when what happened is "that is not a number". A fuzz of
every write route found two dozen views that passed a typed value straight
to the ORM; this is the boundary that turns those into an answer the screen
can show. Everything is still logged with its traceback, so a real bug
hiding behind a 400 is one log line away.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, OperationalError
from django.db.models.deletion import ProtectedError, RestrictedError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)

MALFORMED = "Algún dato no tiene el formato esperado: un número, una fecha o un identificador."
IN_USE = "No se puede borrar: otros registros dependen de él."
CONFLICT = "Los datos chocan con un registro existente o falta un dato obligatorio."
BUSY = "El sistema estaba guardando otro cambio y no llegó a tiempo. Vuelve a intentarlo."


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response
    view = getattr(context.get("view"), "__class__", type(None)).__name__
    if isinstance(exc, (ProtectedError, RestrictedError)):
        logger.warning("delete refused in %s: %s", view, exc)
        return Response({"detail": IN_USE}, status=409)
    if isinstance(exc, IntegrityError):
        logger.exception("integrity error in %s", view)
        return Response({"detail": CONFLICT}, status=409)
    if isinstance(exc, OperationalError) and "locked" in str(exc):
        # Nothing was saved and trying again works: say so, instead of a
        # Django debug page with the server's environment in it.
        logger.exception("database busy in %s", view)
        return Response({"detail": BUSY}, status=503, headers={"Retry-After": "2"})
    if isinstance(exc, (ValueError, DjangoValidationError)):
        logger.warning("malformed input in %s", view, exc_info=exc)
        return Response({"detail": MALFORMED}, status=400)
    return None

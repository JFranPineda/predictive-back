from __future__ import annotations

import importlib

from celery import shared_task


@shared_task(name="core.dispatch_event")
def dispatch_event(event_name: str, handler_path: str, payload: dict) -> None:
    module_path, _, qualname = handler_path.partition(":")
    handler = getattr(importlib.import_module(module_path), qualname)
    handler(payload)

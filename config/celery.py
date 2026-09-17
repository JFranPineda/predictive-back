from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("predictive")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(related_name="infrastructure.tasks")

app.conf.beat_schedule = {
    # R4: the heavy image work runs when nobody is waiting for it.
    "convert-media-nightly": {"task": "media.convert_pending", "schedule": crontab(hour=0, minute=15)},
    "prune-originals": {"task": "media.prune_originals", "schedule": crontab(hour=3, minute=0)},
}

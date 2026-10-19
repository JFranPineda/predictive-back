from __future__ import annotations

from celery import shared_task


@shared_task(name="licensing.renew_online")
def renew_licences():
    """Daily (config/celery.py). Without LICENSE_RENEW_URL it returns before
    touching the database or the network."""
    from django.conf import settings

    if not settings.LICENSE_RENEW_URL:
        return "not_configured"
    from modules.licensing.application.renewal import renew_all_online
    from modules.licensing.infrastructure.keys import trusted_keys
    from modules.licensing.infrastructure.renewal_client import post_json

    return renew_all_online(keys=trusted_keys(), url=settings.LICENSE_RENEW_URL, post=post_json)

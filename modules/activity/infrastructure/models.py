from __future__ import annotations

from django.conf import settings
from django.db import models


class ActivityEvent(models.Model):
    """One thing somebody did in the system (Q20): a click, a page opened, a
    record created, changed or deleted, a file uploaded, a login.

    Not a `TenantModel`: a failed login has no company yet, and the row must
    still be written. Rows are never edited — the log is append-only.
    """

    company = models.ForeignKey(
        "core.Company", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Frozen with the row: a user renamed or deleted later still reads as who
    # they were when they did it.
    user_label = models.CharField(max_length=160, blank=True)
    kind = models.CharField(max_length=20, db_index=True)
    event = models.CharField(max_length=80)
    description = models.CharField(max_length=300)
    path = models.CharField(max_length=200, blank=True)
    method = models.CharField(max_length=8, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-at", "-id"]
        indexes = [
            models.Index(fields=["company", "-at"]),
            models.Index(fields=["company", "user", "-at"]),
        ]

    def __str__(self) -> str:
        return f"{self.at:%Y-%m-%d %H:%M} · {self.user_label} · {self.event}"

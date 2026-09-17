from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from modules.core.infrastructure.models import Company, TimeStampedModel


class UserManager(BaseUserManager):
    def create_user(self, email: str, password: str | None = None, **extra):
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=80, blank=True)
    last_name = models.CharField(max_length=80, blank=True)
    initials = models.CharField(
        max_length=6, blank=True, help_text="As signed in field sheets: CT, HT, JA"
    )
    phone = models.CharField(max_length=30, blank=True)
    language = models.CharField(
        max_length=5, blank=True, choices=[("es", "Español"), ("en", "English")],
        help_text="Empty means the company default",
    )
    is_external = models.BooleanField(
        default=False, help_text="Contractor: reads the asset, writes only his own visits"
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    mfa_enabled = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    objects = UserManager()

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.email


class Permission(models.Model):
    """Declared by module manifests and synced on install. Never hand-written."""

    code = models.CharField(max_length=80, unique=True)
    module_code = models.SlugField(max_length=60, db_index=True)
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.code


class Role(TimeStampedModel):
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, null=True, blank=True, related_name="roles",
        help_text="Null means a system role shared by every company",
    )
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=80)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    class Meta:
        unique_together = [("company", "code")]


class Membership(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    is_default = models.BooleanField(default=False)

    class Meta:
        unique_together = [("user", "company")]


class ScopeRestriction(models.Model):
    """Narrows a membership to some plants or areas. With 558 equipments and
    crews working per area, company-wide access is both unusable and unsafe."""

    SCOPES = [("plant", "Plant"), ("area", "Area")]

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="restrictions"
    )
    scope = models.CharField(max_length=10, choices=SCOPES)
    refs = models.JSONField(default=list)

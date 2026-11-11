from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-for-production")
DEBUG = os.environ.get("DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "django_celery_beat",
]


def _module_apps() -> list[str]:
    """Every discovered module is loaded so its migrations exist; whether it is
    *installed* is a row in core.InstalledModule, not an import."""
    from modules.core.infrastructure.discovery import module_app_labels

    return module_app_labels()


INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + _module_apps()

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Which customer, then may they work today — both before authentication,
    # because "who is this user" can only be asked of the right database.
    "modules.licensing.infrastructure.middleware.TenantMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "modules.licensing.infrastructure.middleware.LicenseMiddleware",
    "modules.core.infrastructure.middleware.RequestContextMiddleware",
    # Outside the gate and the guard, so it also hears what they refused.
    "modules.core.infrastructure.request_observers.RequestObserverMiddleware",
    # Last: it needs the tenant resolved, and runs once the URL is known.
    "modules.core.infrastructure.module_gate.ModuleGateMiddleware",
    # After the gate: a write to an uninstalled module is a 404, not a veto.
    "modules.core.infrastructure.write_guard.WriteGuardMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
AUTH_USER_MODEL = "security.User"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

# Two planes.
#
#   default  — ours. The tenant registry and the licences, nothing else.
#   tenant_* — the customer's, registered at runtime from the registry or from
#              TENANT_<CODE>_DATABASE_URL. It may live on their premises.
#
# Both come from a URL in the environment: no connection detail is ever written
# in code, and onboarding a customer never means editing this file.
from modules.core.domain.database_url import parse as _parse_database_url  # noqa: E402

CONTROL_DATABASE_URL = os.environ.get("CONTROL_DATABASE_URL", "sqlite:///data/control.sqlite3")
DATABASES = {"default": _parse_database_url(CONTROL_DATABASE_URL).as_django()}

DATABASE_ROUTERS = ["modules.licensing.infrastructure.router.TenantRouter"]
TENANT_CONN_MAX_AGE = int(os.environ.get("TENANT_CONN_MAX_AGE", "60"))

# Single-tenant deployments (and every management command) need a default.
DEFAULT_TENANT = os.environ.get("DEFAULT_TENANT", "")
BASE_DOMAIN = os.environ.get("BASE_DOMAIN", "")

# Licences verify with the public half of our Ed25519 key, which ships with the
# program and is never read from the environment.
from modules.licensing.domain import signing_key as _signing_key  # noqa: E402

LICENSE_PUBLIC_KEY = _signing_key.PUBLIC_KEY


# The installation a licence covers (v4 Phase 2). The file lives in the data
# volume, so a restore of that volume keeps the installation's identity and its
# remembered date; the machine id is the server's, never configured.
INSTALLATION_FILE = BASE_DIR / os.environ.get("INSTALLATION_FILE", "data/installation.json")
MACHINE_ID_FILE = "/etc/machine-id"

# Our renewal service (v4 Phase 3), e.g. https://renovacion.example/renew.
# Empty: the daily check does nothing and never goes online; renewing is by
# file only. The customer's IT decides whether this server may reach it.
LICENSE_RENEW_URL = os.environ.get("LICENSE_RENEW_URL", "")

# Where full exports are prepared for download (v4 Phase 4). Only the latest
# per tenant is kept: each is a copy of everything, files included.
EXPORT_ROOT = BASE_DIR / os.environ.get("EXPORT_ROOT", "data/exports")

# A sealed build (v4 Phase 5) is stamped with the customer, version and build
# id; the PDFs it makes name them. Empty on a source checkout.
BUILD_TENANT = os.environ.get("BUILD_TENANT", "")
BUILD_VERSION = os.environ.get("BUILD_VERSION", "")
BUILD_ID = os.environ.get("BUILD_ID", "")

# The signed list of files the sealed build ships. Present only in a release
# image; where it is, the program verifies it at startup and refuses to run if
# a file was altered (modules/licensing/infrastructure/integrity_check.py).
INTEGRITY_MANIFEST = BASE_DIR / "integrity.manifest"
INTEGRITY_SIGNATURE = BASE_DIR / "integrity.sig"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "modules.security.interfaces.authentication.TenantJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "modules.core.interfaces.errors.exception_handler",
    # An eight-character code is only as strong as the guesses it allows.
    # Ten a minute per address makes brute force take longer than the code
    # lives; a technician who mistypes twice never notices the limit.
    "DEFAULT_THROTTLE_RATES": {"code_login": "10/min"},
}

# No inactivity logout (decided 2026-11-11): it signed people out in the
# middle of a demo. The refresh token lasts thirty days (SESSION_DAYS) and
# rotates on every use, the old one blacklisted; the client renews the short
# access token ahead of expiry while the browser holds the session. It ends
# when the user signs out, or after thirty days without the app open.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.environ.get("ACCESS_MINUTES", "5"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.environ.get("SESSION_DAYS", "30"))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Predictive API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

from celery.schedules import crontab  # noqa: E402

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_ROUTES = {"media.*": {"queue": "media"}}
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
# The heavy image work runs when nobody is waiting for it (doc 05). A
# deployment without a broker runs the same code from `manage.py media_convert`.
CELERY_BEAT_SCHEDULE = {
    "media-convert-pending": {
        "task": "media.convert_pending",
        "schedule": crontab(hour=0, minute=15),
    },
}

# `local` keeps files on disk, which is what a single-server install and
# every developer machine actually has; `s3` signs URLs against object storage.
MEDIA_BACKEND = os.environ.get("MEDIA_BACKEND", "local")
MEDIA_ROOT = BASE_DIR / os.environ.get("MEDIA_ROOT", "data/media")

# Where the logs older than the screens' fortnight are filed, one CSV per
# month per log. A plain folder on purpose: an auditor opens it with Excel.
HISTORY_ROOT = BASE_DIR / os.environ.get("HISTORY_ROOT", "data/history")
MEDIA_URL = "/media/"

OBJECT_STORE_ENDPOINT = os.environ.get("OBJECT_STORE_ENDPOINT", "http://localhost:9000")
OBJECT_STORE_BUCKET = os.environ.get("OBJECT_STORE_BUCKET", "predictive")
OBJECT_STORE_KEY = os.environ.get("OBJECT_STORE_KEY", "minioadmin")
OBJECT_STORE_SECRET = os.environ.get("OBJECT_STORE_SECRET", "minioadmin")
OBJECT_STORE_REGION = os.environ.get("OBJECT_STORE_REGION", "us-east-1")

CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")

LANGUAGE_CODE = "es"
LANGUAGES = [("es", "Español"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "America/Lima"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

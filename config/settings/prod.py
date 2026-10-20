import os

from .base import *  # noqa: F403

DEBUG = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
# Behind the installation's TLS-terminating proxy, which says the original
# request was HTTPS. Without this every request looked like plain HTTP and was
# redirected to HTTPS forever (found in docs/v4, Phase 5). The application
# port must only be reachable through that proxy, or a client could claim
# HTTPS on its own.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
ALLOWED_HOSTS = os.environ["ALLOWED_HOSTS"].split(",")

# Shared, not per process. The code-login throttle counts guesses in the cache,
# and the default in-memory cache keeps one counter per worker: four gunicorn
# workers would quietly allow four times the guesses the limit promises.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/1"),
    }
}

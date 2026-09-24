import os

from .base import *  # noqa: F403

DEBUG = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
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

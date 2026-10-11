"""Azure App Service settings; secrets are supplied by the host, never a local .env."""

import os

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403
from .settings import DATABASES, MIDDLEWARE, SECRET_KEY, required_env

if os.environ.get("DJANGO_DEBUG", "false").lower() != "false":
    raise ImproperlyConfigured("DJANGO_DEBUG must be false in production.")
DEBUG = False

MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(1, "config.middleware.AllowedHostMiddleware")
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong production signing secret.")
ANSWER_HMAC_KEY = required_env("ANSWER_HMAC_KEY")
if len(ANSWER_HMAC_KEY) < 32 or "change-before-sharing" in ANSWER_HMAC_KEY:
    raise ImproperlyConfigured("ANSWER_HMAC_KEY must be a strong persistent signing secret.")

ALLOWED_HOSTS = [host.strip() for host in required_env("DJANGO_ALLOWED_HOSTS").split(",")]
if any(not host or "*" in host or host.startswith(".") or "://" in host for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must list explicit hostnames.")
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in required_env("DJANGO_CSRF_TRUSTED_ORIGINS").split(",")
]
if any(not origin.startswith("https://") or "*" in origin for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured("Production CSRF origins must be explicit HTTPS origins.")

# Enable only behind a proxy that overwrites this header (Azure App Service).
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if os.environ.get("DJANGO_TRUST_PROXY_SSL_HEADER", "false").lower() == "true"
    else None
)
SECURE_SSL_REDIRECT = True
# App Service's internal readiness probe may use HTTP; it exposes no event data.
SECURE_REDIRECT_EXEMPT = [r"^api/health$"]
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

DATABASES["default"]["HOST"] = required_env("POSTGRES_HOST")
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["OPTIONS"] = {
    "connect_timeout": 5,
    "sslmode": "verify-full",
    "sslrootcert": os.environ.get("POSTGRES_SSLROOTCERT", "system"),
    "options": (
        "-c statement_timeout=30000 -c lock_timeout=5000 "
        "-c idle_in_transaction_session_timeout=30000"
    ),
}

# Log errors to the platform stream without request bodies, credentials or query strings.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {"django": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
}

"""Exercise production settings in a fresh process without secrets or a database."""

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def production_process(code, overrides=None):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DJANGO_", "POSTGRES_", "ANSWER_"))
    }
    env.update(
        DJANGO_SETTINGS_MODULE="config.settings_production",
        DJANGO_SECRET_KEY="production-test-only-" + "abcdefghijklmnopqrstuvwxyz0123456789" * 2,
        ANSWER_HMAC_KEY="test-only-persistent-answer-signing-key",
        DJANGO_ALLOWED_HOSTS="hunt.example.com, hunt.azurewebsites.net",
        DJANGO_CSRF_TRUSTED_ORIGINS="https://hunt.example.com",
        DJANGO_TRUST_PROXY_SSL_HEADER="true",
        POSTGRES_DB="test",
        POSTGRES_USER="test",
        POSTGRES_PASSWORD="test-only",
        POSTGRES_HOST="test.postgres.database.azure.com",
    )
    for key, value in (overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True
    )


def test_production_deployment_checks_only_warn_about_intentional_no_preload():
    result = production_process(
        "import django; django.setup(); "
        "from django.core.checks import run_checks; "
        "issues = run_checks(include_deployment_checks=True); "
        "assert [issue.id for issue in issues] == ['security.W021'], issues"
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DJANGO_DEBUG", "true"),
        ("DJANGO_SECRET_KEY", "local-development-only-change-before-sharing"),
        ("ANSWER_HMAC_KEY", None),
        ("ANSWER_HMAC_KEY", "local-answer-key-change-before-sharing"),
        ("POSTGRES_HOST", None),
        ("POSTGRES_PASSWORD", None),
        ("DJANGO_ALLOWED_HOSTS", None),
        ("DJANGO_ALLOWED_HOSTS", "*"),
        ("DJANGO_CSRF_TRUSTED_ORIGINS", "http://hunt.example.com"),
    ],
)
def test_production_rejects_unsafe_or_missing_configuration(name, value):
    result = production_process("import config.settings_production", {name: value})
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr


def test_production_https_redirect_proxy_and_cookie_behavior():
    result = production_process(
        "import django; django.setup(); "
        "from django.test import Client; "
        "client = Client(HTTP_HOST='hunt.example.com'); "
        "assert client.get('/api/auth/csrf').status_code == 301; "
        "response = client.get('/api/auth/csrf', HTTP_X_FORWARDED_PROTO='https'); "
        "assert response.status_code == 200; "
        "assert response.cookies['csrftoken']['secure']; "
        "assert response['Strict-Transport-Security']; "
        "assert response['Cache-Control'] == 'no-store'; "
        "assert client.get('/api/auth/csrf', HTTP_HOST='evil.example').status_code == 400; "
        "assert client.get('/api/auth/csrf', HTTP_HOST='evil.example', "
        "HTTP_X_FORWARDED_PROTO='https').status_code == 400; "
        "assert client.get('/api/health', HTTP_HOST='evil.example').status_code == 400; "
        "from unittest.mock import patch; "
        "probe = patch('config.views.connection.cursor'); probe.start(); "
        "assert client.get('/api/health').status_code == 200; probe.stop()"
    )
    assert result.returncode == 0, result.stderr


def test_production_database_requires_verified_tls():
    result = production_process(
        "import json; from django.conf import settings; "
        "print(json.dumps(settings.DATABASES['default']['OPTIONS']))"
    )
    assert result.returncode == 0, result.stderr
    options = json.loads(result.stdout)
    assert options["sslmode"] == "verify-full"
    assert options["sslrootcert"] == "system"


def test_proxy_header_is_not_trusted_without_opt_in():
    result = production_process(
        "from django.conf import settings; assert settings.SECURE_PROXY_SSL_HEADER is None",
        {"DJANGO_TRUST_PROXY_SSL_HEADER": None},
    )
    assert result.returncode == 0, result.stderr


def test_production_serves_collected_admin_static_files(tmp_path):
    result = production_process(
        "import django; django.setup(); "
        "from django.test import Client, override_settings; "
        "from django.core.management import call_command; "
        f"root = {str(tmp_path / 'staticfiles')!r}; "
        "override = override_settings(STATIC_ROOT=root); override.enable(); "
        "call_command('collectstatic', interactive=False, verbosity=0); "
        "response = Client(HTTP_HOST='hunt.example.com').get("
        "'/static/admin/css/base.css', HTTP_X_FORWARDED_PROTO='https'); "
        "assert response.status_code == 200; "
        "assert response['Content-Type'].startswith('text/css'); "
        "assert 'X-Request-ID' in response"
    )
    assert result.returncode == 0, result.stderr


def test_backend_package_excludes_local_secrets_content_and_development_files(tmp_path):
    output = tmp_path / "backend.zip"
    result = subprocess.run(
        [sys.executable, str(BACKEND.parent / "tools/package_backend.py"), "--output", str(output)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert {"manage.py", "config/wsgi.py", "startup.sh", "requirements.txt"} <= names
        assert "config/settings_production.py" in names
        assert any(name.startswith("competition/migrations/") for name in names)
        assert all(
            name.endswith(".py") or name in {"startup.sh", "requirements.txt"} for name in names
        )
        assert not any(
            name.startswith((".env", ".local", "tests/", "frontend/", "docs/")) for name in names
        )
        requirements = archive.read("requirements.txt").decode()
        assert "gunicorn==" in requirements and "whitenoise==" in requirements
        assert "pytest" not in requirements and "ruff" not in requirements
        assert b"\r" not in archive.read("startup.sh")
    repeat = subprocess.run(
        [sys.executable, str(BACKEND.parent / "tools/package_backend.py"), "--output", str(output)],
        capture_output=True,
        text=True,
    )
    assert repeat.returncode != 0
    assert "FileExistsError" in repeat.stderr

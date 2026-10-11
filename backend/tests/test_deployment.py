"""Exercise production settings in a fresh process without secrets or a database."""

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def production_process(code, overrides=None, *, cwd=BACKEND):
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
        [sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True
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


def test_production_always_enforces_staff_mfa_and_denies_api_before_database_access():
    result = production_process(
        "import django; django.setup(); "
        "from django.conf import settings; "
        "from django.test import Client; "
        "assert settings.STAFF_MFA_REQUIRED is True; "
        "assert 'django_otp.middleware.OTPMiddleware' in settings.MIDDLEWARE; "
        "client = Client(HTTP_HOST='hunt.example.com', HTTP_X_FORWARDED_PROTO='https'); "
        "response = client.get('/api/staff/rounds'); "
        "assert response.status_code == 403; "
        "assert response.json()['error']['code'] == 'staff_login_required'",
        {"STAFF_MFA_REQUIRED": "false"},
    )
    assert result.returncode == 0, result.stderr


def test_production_images_use_private_azure_storage_without_local_fallback():
    result = production_process(
        "import django; django.setup(); "
        "from django.core.files.storage import storages; "
        "from django.core.exceptions import ImproperlyConfigured; "
        "storage = storages['mission_images']; "
        "assert storage.__class__.__name__ == 'PrivateAzureStorage'; "
        "assert storage.overwrite_files is False; "
        "assert storage.token_credential is not None\n"
        "try:\n storage.url('private.png')\n"
        "except ValueError:\n pass\n"
        "else:\n raise AssertionError('A public image URL was exposed')\n"
        "try:\n storage.exists('private.png')\n"
        "except ImproperlyConfigured:\n pass\n"
        "else:\n raise AssertionError('Missing storage configuration was accepted')\n",
        {"AZURE_MISSION_ACCOUNT_NAME": ""},
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
            name.endswith(".py")
            or name in {"startup.sh", "requirements.txt"}
            or name.startswith("competition/templates/staff_mfa/")
            and name.endswith(".html")
            for name in names
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


def test_production_frontend_deep_links_and_asset_cache_policy(tmp_path):
    frontend = tmp_path / "frontend_dist"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text('<html><div id="root">Public shell</div></html>')
    (frontend / "assets/app-12345678.js").write_text("console.log('public test bundle')")
    (frontend / "assets/plain.js").write_text("console.log('unhashed test file')")
    result = production_process(
        "from pathlib import Path; import django; django.setup(); "
        "from django.test import Client, override_settings; "
        "from django.core.management import call_command; "
        f"override = override_settings(FRONTEND_DIST_DIR=Path({str(frontend)!r}), "
        f"STATIC_ROOT={str(tmp_path / 'staticfiles')!r}, "
        f"STATICFILES_DIRS=[('frontend/assets', {str(frontend / 'assets')!r})]); "
        "override.enable(); call_command('collectstatic', interactive=False, verbosity=0); "
        "client = Client(HTTP_HOST='hunt.example.com', HTTP_X_FORWARDED_PROTO='https'); "
        "routes = ['/', '/login', '/lobby', '/rounds/5', '/rounds/3/coding', "
        "'/rounds/1/results', '/missions/qr-token', '/staff/rounds', '/staff/buzzer', "
        "'/staff/scores', '/staff/results', '/staff/roster', '/staff/coding']; "
        "responses = [client.get(route) for route in routes]; "
        "assert all(r.status_code == 200 for r in responses); "
        "assert all(r['Cache-Control'] == 'no-store' for r in responses); "
        "assert client.head('/login').status_code == 200; "
        "assert client.post('/login').status_code == 405; "
        "missing = ['/api/missing', '/static/missing.js', "
        "'/static/frontend/index.html', '/.env', '/frontend_dist/index.html', "
        "'/unknown', '/rounds/1/unknown', '/missions/a/b']; "
        "assert all(client.get(path).status_code == 404 for path in missing); "
        "asset = client.get('/static/frontend/assets/app-12345678.js'); "
        "assert asset.status_code == 200; "
        "assert 'immutable' in asset['Cache-Control']; "
        "plain = client.get('/static/frontend/assets/plain.js'); "
        "assert 'immutable' not in plain['Cache-Control']; "
        "assert client.get('/api/auth/csrf')['Content-Type'] == 'application/json'; "
        "assert client.get('/admin/').status_code == 302"
    )
    assert result.returncode == 0, result.stderr


def test_backend_only_release_still_returns_404_for_frontend_routes(tmp_path):
    result = production_process(
        "from pathlib import Path; import django; django.setup(); "
        "from django.test import Client, override_settings; "
        f"override_settings(FRONTEND_DIST_DIR=Path({str(tmp_path / 'absent')!r})).enable(); "
        "client = Client(HTTP_HOST='hunt.example.com', HTTP_X_FORWARDED_PROTO='https'); "
        "assert client.get('/').status_code == 404; "
        "assert client.get('/login').status_code == 404; "
        "assert client.get('/api/auth/csrf').status_code == 200"
    )
    assert result.returncode == 0, result.stderr


def frontend_fixture(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / ".vite").mkdir()
    (dist / ".vite/manifest.json").write_text(
        json.dumps({"index.html": {"isEntry": True, "file": "assets/app-12345678.js"}})
    )
    (dist / "index.html").write_text(
        '<script type="module" src="/static/frontend/assets/app-12345678.js"></script>'
    )
    (dist / "assets/app-12345678.js").write_text("console.log('fixture')")
    return dist


def package_frontend(dist, output):
    return subprocess.run(
        [
            sys.executable,
            str(BACKEND.parent / "tools/package_backend.py"),
            "--frontend-dist",
            str(dist),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )


def test_website_package_includes_only_compiled_frontend_and_preserves_binary_assets(tmp_path):
    dist = frontend_fixture(tmp_path)
    binary = b"binary-test\r\n\x00\xff"
    (dist / "assets/image-12345678.png").write_bytes(binary)
    output = tmp_path / "website.zip"
    result = package_frontend(dist, output)
    assert result.returncode == 0, result.stderr
    assert "SHA256:" in result.stdout
    with zipfile.ZipFile(output) as archive:
        assert archive.read("frontend_dist/assets/image-12345678.png") == binary
        assert "frontend_dist/index.html" in archive.namelist()
        assert "config/settings_production.py" in archive.namelist()
        assert not any(name.startswith("frontend_dist/.vite/") for name in archive.namelist())


@pytest.mark.parametrize("extra", [".env", "host-answers.json", "assets/app-12345678.js.map"])
def test_website_package_rejects_unexpected_private_files_or_source_maps(tmp_path, extra):
    dist = frontend_fixture(tmp_path)
    (dist / extra).write_text("private test fixture")
    output = tmp_path / "website.zip"
    result = package_frontend(dist, output)
    assert result.returncode != 0
    assert "Unexpected frontend build file" in result.stderr
    assert not output.exists()


def test_website_package_rejects_missing_or_wrongly_based_assets(tmp_path):
    dist = frontend_fixture(tmp_path)
    (dist / "index.html").write_text('<script src="/assets/app-12345678.js"></script>')
    result = package_frontend(dist, tmp_path / "wrong-base.zip")
    assert result.returncode != 0
    (dist / "index.html").write_text(
        '<script src="/static/frontend/assets/app-12345678.js"></script>'
    )
    (dist / "assets/app-12345678.js").unlink()
    result = package_frontend(dist, tmp_path / "missing.zip")
    assert result.returncode != 0
    assert "Missing or incorrectly configured frontend asset" in result.stderr


@pytest.mark.skipif(
    not (BACKEND.parent / "frontend/dist/.vite/manifest.json").is_file(),
    reason="Run npm run build in frontend to test the real compiled release.",
)
def test_real_website_package_serves_build_using_production_settings(tmp_path):
    output = tmp_path / "website.zip"
    result = package_frontend(BACKEND.parent / "frontend/dist", output)
    assert result.returncode == 0, result.stderr
    release = tmp_path / "release"
    with zipfile.ZipFile(output) as archive:
        archive.extractall(release)
    result = production_process(
        "import re; import django; django.setup(); "
        "from django.core.management import call_command; "
        "from django.test import Client; "
        "call_command('collectstatic', interactive=False, verbosity=0); "
        "client = Client(HTTP_HOST='hunt.example.com', HTTP_X_FORWARDED_PROTO='https'); "
        "response = client.get('/login'); "
        "assert response.status_code == 200; "
        "html = b''.join(response.streaming_content).decode(); "
        'assets = re.findall(r\'(?:src|href)="(/static/frontend/assets/[^"]+)"\', html); '
        "assert len(assets) >= 2; "
        "responses = [client.get(url) for url in assets]; "
        "assert all(r.status_code == 200 for r in responses); "
        "assert all('immutable' in r['Cache-Control'] for r in responses); "
        "assert client.get('/api/auth/csrf').status_code == 200; "
        "assert client.get('/api/not-a-route').status_code == 404; "
        "assert client.get('/staff/buzzer').status_code == 200",
        cwd=release,
    )
    assert result.returncode == 0, result.stderr

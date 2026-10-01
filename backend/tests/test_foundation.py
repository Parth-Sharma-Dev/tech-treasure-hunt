from unittest.mock import MagicMock, patch
from uuid import UUID

from django.db import OperationalError
from django.test import Client
from rest_framework.exceptions import PermissionDenied

from config.exceptions import api_exception_handler


def test_health_success_includes_request_id_and_disables_caching(client):
    with patch("config.views.connection.cursor") as cursor:
        cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert str(UUID(response.json()["request_id"])) == response["X-Request-ID"]
    assert response["Cache-Control"] == "no-store"
    cursor.return_value.__enter__.return_value.execute.assert_called_once_with("SELECT 1")


def test_health_failure_does_not_expose_database_secrets(client):
    with patch("config.views.connection.cursor", side_effect=OperationalError("secret password")):
        response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert "secret" not in response.content.decode()


def test_csrf_cookie_and_token_are_available():
    response = Client(enforce_csrf_checks=True).get("/api/auth/csrf")
    assert response.status_code == 200
    assert response.cookies["csrftoken"]["samesite"] == "Lax"
    assert len(response.json()["csrf_token"]) == 64


def test_health_is_read_only(client):
    assert client.post("/api/health").status_code == 405


def test_permission_errors_have_consistent_envelope():
    request = MagicMock(request_id="test-request")
    response = api_exception_handler(PermissionDenied(), {"request": request})
    assert response.status_code == 403
    assert response.data["request_id"] == "test-request"
    assert response.data["error"]["code"] == "permission_denied"

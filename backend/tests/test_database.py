import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.db import connection


@pytest.mark.django_db
def test_postgresql_connection_and_durable_sessions():
    assert connection.vendor == "postgresql"
    session = SessionStore()
    session["foundation_probe"] = "saved"
    session.save()
    assert SessionStore(session_key=session.session_key)["foundation_probe"] == "saved"
    session.delete()

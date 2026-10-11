from competition.management.commands.backup_competition import pg_connection_options, pg_environment


def database_config():
    return {
        "HOST": "test.postgres.database.azure.com",
        "PORT": "5432",
        "NAME": "event",
        "USER": "test",
        "PASSWORD": "test-only",
        "OPTIONS": {
            "sslmode": "verify-full",
            "sslrootcert": "system",
            "connect_timeout": 5,
            "options": "-c statement_timeout=30000",
        },
    }


def test_backup_tools_use_configured_tls_instead_of_weaker_inherited_environment(monkeypatch):
    monkeypatch.setenv("PGSSLMODE", "disable")
    env = pg_environment(database_config())
    assert env["PGSSLMODE"] == "verify-full"
    assert env["PGSSLROOTCERT"] == "system"
    assert env["PGCONNECT_TIMEOUT"] == "5"
    assert env["PGDATABASE"] == "event"


def test_recovery_target_changes_database_and_preserves_tls():
    env = pg_environment(database_config(), "tth_recovery_test")
    assert env["PGDATABASE"] == "tth_recovery_test"
    assert env["PGSSLMODE"] == "verify-full"


def test_direct_recovery_connection_preserves_tls_without_live_query_timeouts():
    assert pg_connection_options(database_config()) == {
        "sslmode": "verify-full",
        "sslrootcert": "system",
        "connect_timeout": 5,
    }
    assert pg_connection_options({}) == {}

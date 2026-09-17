"""Every connection — ours and each customer's on-premise one — is an env var."""

import pytest

from modules.core.domain.database_url import InvalidDatabaseUrl, parse


class TestPostgres:
    url = "postgres://predictive:s3cr3t@db.cliente.com:5433/predictive_ambev"

    def test_splits_the_url_into_django_settings(self):
        config = parse(self.url)
        assert config.engine == "django.db.backends.postgresql"
        assert (config.name, config.user, config.password) == (
            "predictive_ambev", "predictive", "s3cr3t",
        )
        assert (config.host, config.port) == ("db.cliente.com", "5433")

    def test_accepts_both_postgres_spellings(self):
        assert parse(self.url).engine == parse(self.url.replace("postgres:", "postgresql:")).engine

    def test_decodes_a_password_with_symbols(self):
        config = parse("postgres://user:p%40ss%2Fword@host:5432/db")
        assert config.password == "p@ss/word"

    def test_carries_ssl_settings_into_driver_options(self):
        config = parse(f"{self.url}?sslmode=verify-full&connect_timeout=5")
        assert config.options == {"sslmode": "verify-full", "connect_timeout": "5"}

    def test_refuses_options_it_does_not_understand(self):
        # Dropping them silently is how a customer's sslmode=verify-full stops
        # being enforced without anyone noticing.
        with pytest.raises(InvalidDatabaseUrl, match="pool_size"):
            parse(f"{self.url}?pool_size=20")

    def test_builds_a_django_dict(self):
        settings = parse(self.url).as_django()
        assert settings["ENGINE"] == "django.db.backends.postgresql"
        assert settings["NAME"] == "predictive_ambev"
        assert settings["CONN_MAX_AGE"] == 60

    def test_redacts_the_password_for_logs_and_admin(self):
        redacted = parse(self.url).redacted()
        assert "s3cr3t" not in redacted
        assert "db.cliente.com:5433/predictive_ambev" in redacted


class TestSqlite:
    def test_relative_file(self):
        config = parse("sqlite:///data/demo.sqlite3")
        assert config.is_sqlite and config.name == "data/demo.sqlite3"

    def test_absolute_file(self):
        assert parse("sqlite:////var/lib/predictive.db").name == "/var/lib/predictive.db"

    def test_in_memory(self):
        assert parse("sqlite://:memory:").name == ":memory:"

    def test_never_keeps_connections_open(self):
        # A persistent sqlite connection across threads is a locked database.
        assert parse("sqlite:///demo.db").as_django()["CONN_MAX_AGE"] == 0


class TestRejections:
    @pytest.mark.parametrize("url", ["", "not-a-url", "/var/lib/db"])
    def test_something_that_is_not_a_url(self, url):
        with pytest.raises(InvalidDatabaseUrl):
            parse(url)

    def test_an_engine_we_do_not_support(self):
        with pytest.raises(InvalidDatabaseUrl, match="oracle"):
            parse("oracle://user:pass@host/db")

    def test_postgres_without_a_database_name(self):
        with pytest.raises(InvalidDatabaseUrl, match="database name"):
            parse("postgres://user:pass@host:5432/")

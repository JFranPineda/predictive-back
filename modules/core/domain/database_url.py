"""`DATABASE_URL` parsing.

Every connection in this system — ours and every customer's on-premise one —
is described by a URL in an env var. No connection details live in code, and
adding a customer never means editing `settings.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlparse

ENGINES = {
    "postgres": "django.db.backends.postgresql",
    "postgresql": "django.db.backends.postgresql",
    "psql": "django.db.backends.postgresql",
    "sqlite": "django.db.backends.sqlite3",
    "mysql": "django.db.backends.mysql",
}

# Query parameters that belong in the driver's OPTIONS rather than at top level.
DRIVER_OPTIONS = frozenset({"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout",
                            "application_name", "options", "target_session_attrs"})


class InvalidDatabaseUrl(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    engine: str
    name: str
    user: str = ""
    password: str = ""
    host: str = ""
    port: str = ""
    options: dict[str, str] = field(default_factory=dict)
    conn_max_age: int = 60

    @property
    def is_sqlite(self) -> bool:
        return self.engine.endswith("sqlite3")

    def as_django(self) -> dict:
        settings: dict = {
            "ENGINE": self.engine,
            "NAME": self.name,
            "USER": self.user,
            "PASSWORD": self.password,
            "HOST": self.host,
            "PORT": self.port,
            "OPTIONS": dict(self.options),
            "ATOMIC_REQUESTS": False,
            "AUTOCOMMIT": True,
            "TIME_ZONE": None,
            "CONN_MAX_AGE": 0 if self.is_sqlite else self.conn_max_age,
            "CONN_HEALTH_CHECKS": not self.is_sqlite,
            "TEST": {"CHARSET": None, "COLLATION": None, "MIGRATE": True, "MIRROR": None, "NAME": None},
        }
        return settings

    def redacted(self) -> str:
        """Safe to log and to show in the admin. Never print the raw URL."""
        if self.is_sqlite:
            return f"sqlite:///{self.name}"
        where = f"{self.host}:{self.port}" if self.port else self.host
        return f"{self.engine.rsplit('.', 1)[-1]}://{self.user}:***@{where}/{self.name}"


def parse(url: str, *, conn_max_age: int = 60) -> DatabaseConfig:
    if not url or "://" not in url:
        raise InvalidDatabaseUrl(f"'{url}' is not a database URL")

    parsed = urlparse(url)
    scheme = parsed.scheme.split("+")[0].lower()
    engine = ENGINES.get(scheme)
    if engine is None:
        raise InvalidDatabaseUrl(f"unsupported scheme '{parsed.scheme}'")

    if engine.endswith("sqlite3"):
        # Three slashes is a relative path, four is absolute — the same
        # convention every DATABASE_URL tool uses:
        #   sqlite:///data/demo.db    -> data/demo.db
        #   sqlite:////var/lib/x.db   -> /var/lib/x.db
        #   sqlite://:memory:         -> :memory:
        raw = f"{parsed.netloc}{parsed.path}"
        if raw in (":memory:", ""):
            name = ":memory:"
        else:
            name = raw[1:] if raw.startswith("/") else raw
        return DatabaseConfig(engine=engine, name=name, conn_max_age=0)

    name = unquote(parsed.path.lstrip("/"))
    if not name:
        raise InvalidDatabaseUrl("missing database name")

    query = dict(parse_qsl(parsed.query))
    options = {key: value for key, value in query.items() if key in DRIVER_OPTIONS}
    unknown = set(query) - DRIVER_OPTIONS
    if unknown:
        # Silently dropping them is how a customer's `sslmode=verify-full`
        # quietly stops being enforced.
        raise InvalidDatabaseUrl(f"unknown connection options: {', '.join(sorted(unknown))}")

    return DatabaseConfig(
        engine=engine,
        name=name,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        host=parsed.hostname or "",
        port=str(parsed.port) if parsed.port else "",
        options=options,
        conn_max_age=conn_max_age,
    )

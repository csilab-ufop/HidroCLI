# BSD 2-Clause License

# Copyright (c) 2026, base

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:

# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Alembic migration runner shared by ``init_db`` and ``hidro-orm``."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from hidro_orm.schema import (
    BASELINE_REVISION,
    DbKind,
    make_include_object,
    metadata_for,
    sqlite_url,
)

__all__ = [
    "BASELINE_REVISION",
    "LegacyDatabaseError",
    "MigrationError",
    "SchemaDriftError",
    "check",
    "current",
    "heads",
    "history",
    "stamp",
    "upgrade",
    "upgrade_or_raise",
]


class MigrationError(RuntimeError):
    """Base error for migration operations."""


class LegacyDatabaseError(MigrationError):
    """Raised when a database needs an explicit one-time stamp."""


class SchemaDriftError(MigrationError):
    """Raised when a database does not match the expected schema."""


def _script_location(kind: DbKind) -> Path:
    return Path(__file__).resolve().parent / "migrations" / kind.value


def _config(kind: DbKind, db_path: str | Path | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(_script_location(kind)))
    if db_path is not None:
        config.set_main_option("sqlalchemy.url", sqlite_url(db_path))
    return config


def _engine(db_path: str | Path) -> Engine:
    return create_engine(sqlite_url(db_path))


def _user_tables(engine: Engine) -> set[str]:
    return {
        name
        for name in inspect(engine).get_table_names()
        if not name.startswith("sqlite_")
    }


def _current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _legacy_message(kind: DbKind, db_path: Path) -> str:
    flag = "--hidro" if kind is DbKind.HIDRO else "--client"
    return (
        f"Database '{db_path}' is not Alembic-versioned.\n"
        "Run once:\n"
        f"  hidro-orm {flag} {db_path} {kind.value} stamp {BASELINE_REVISION}"
    )


def _compare(engine: Engine, kind: DbKind) -> list:
    metadata = metadata_for(kind)
    include_object = make_include_object(metadata)
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": include_object,
            },
        )
        return compare_metadata(context, metadata)


def _format_diff(db_path: Path, diff: list) -> str:
    lines = [f"Schema drift detected in '{db_path}':"]
    lines.extend(f"  {item}" for item in diff)
    lines.append("No version row was written.")
    return "\n".join(lines)


@contextmanager
def _quiet_alembic():
    logger = logging.getLogger("alembic")
    previous = logger.level
    logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        logger.setLevel(previous)


def upgrade(
    kind: DbKind | str,
    db_path: str | Path,
    revision: str = "head",
    *,
    quiet: bool = False,
) -> None:
    """Upgrade ``db_path`` to ``revision``.

    Empty databases are initialized from the baseline revision.  A database
    that already contains tables but has no ``alembic_version`` table is
    rejected so that it can be adopted explicitly with :func:`stamp`.
    """

    kind = DbKind(kind)
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    engine = _engine(path)
    try:
        tables = _user_tables(engine)
        if tables and "alembic_version" not in tables:
            raise LegacyDatabaseError(_legacy_message(kind, path))
    finally:
        engine.dispose()

    config = _config(kind, path)
    if quiet:
        with _quiet_alembic():
            command.upgrade(config, revision)
    else:
        command.upgrade(config, revision)


def upgrade_or_raise(db_path: str | Path, kind: DbKind | str) -> None:
    """Run the startup upgrade with Alembic logging kept quiet."""

    upgrade(kind, db_path, "head", quiet=True)


def stamp(
    kind: DbKind | str,
    db_path: str | Path,
    revision: str = BASELINE_REVISION,
) -> str:
    """Adopt a legacy database by writing ``revision`` without table DDL.

    The current schema is compared with the ORM metadata first.  If anything
    differs, the stamp is aborted and no version row is written.
    """

    kind = DbKind(kind)
    path = Path(db_path).expanduser()
    if not path.exists():
        raise MigrationError(f"Database '{path}' does not exist.")

    engine = _engine(path)
    try:
        tables = _user_tables(engine)
        user_tables = tables - {"alembic_version"}
        if not user_tables:
            raise MigrationError(f"Refusing to stamp empty database '{path}'.")

        if "alembic_version" in tables:
            current_revision = _current_revision(engine)
            if current_revision == revision:
                return current_revision
            if current_revision:
                raise MigrationError(
                    f"Database '{path}' is already stamped at {current_revision}."
                )

        diff = _compare(engine, kind)
        if diff:
            raise SchemaDriftError(_format_diff(path, diff))
    finally:
        engine.dispose()

    command.stamp(_config(kind, path), revision)
    return revision


def current(kind: DbKind | str, db_path: str | Path) -> str:
    """Return the current revision, ``unstamped``, or ``missing``."""

    kind = DbKind(kind)
    path = Path(db_path).expanduser()
    if not path.exists():
        return "missing"

    engine = _engine(path)
    try:
        tables = _user_tables(engine)
        if "alembic_version" not in tables:
            return "unstamped"
        return _current_revision(engine) or "unstamped"
    finally:
        engine.dispose()


def check(kind: DbKind | str, db_path: str | Path) -> list:
    """Return metadata differences for a stamped database."""

    kind = DbKind(kind)
    path = Path(db_path).expanduser()
    if not path.exists():
        raise MigrationError(f"Database '{path}' does not exist.")

    engine = _engine(path)
    try:
        tables = _user_tables(engine)
        if "alembic_version" not in tables:
            raise LegacyDatabaseError(_legacy_message(kind, path))
        return _compare(engine, kind)
    finally:
        engine.dispose()


def history(kind: DbKind | str) -> list:
    """Return the revision chain for ``kind``."""

    kind = DbKind(kind)
    return list(ScriptDirectory.from_config(_config(kind)).walk_revisions())


def heads(kind: DbKind | str) -> tuple[str, ...]:
    """Return the head revisions for ``kind``."""

    kind = DbKind(kind)
    return ScriptDirectory.from_config(_config(kind)).get_heads()

"""Tests for the Hidro/Client Alembic migrations and the hidro-orm CLI."""

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import (
    Column,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    inspect,
    select,
    text,
)

import hidrocli.database.client as client_database
import hidrocli.database.hidro as hidro_database
from hidrocli.database import init_db
from hidrocli.models.client import ClientBase, SeriesJobs
from hidrocli.models.hidro import HidroBase
from hidro_orm import cli, runner
from hidro_orm.schema import BASELINE_REVISION, DbKind, sqlite_url


@pytest.fixture(autouse=True)
def restore_database_globals():
    """Keep init_db tests from leaking global connections into other tests."""

    old_hidro = hidro_database.HIDRO_DB
    old_client = client_database.CLIENT_DB
    yield

    for current, old in (
        (hidro_database.HIDRO_DB, old_hidro),
        (client_database.CLIENT_DB, old_client),
    ):
        if current is not None and current is not old:
            current.close()

    hidro_database.HIDRO_DB = old_hidro
    client_database.CLIENT_DB = old_client


def _table_names(db_path: str) -> set[str]:
    engine = create_engine(sqlite_url(db_path))
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_hidro_upgrade_creates_schema(tmp_path):
    db_path = str(tmp_path / "hidro.db")

    runner.upgrade(DbKind.HIDRO, db_path)

    assert runner.current(DbKind.HIDRO, db_path) == BASELINE_REVISION
    assert _table_names(db_path) == set(HidroBase.metadata.tables) | {
        "alembic_version"
    }
    assert runner.check(DbKind.HIDRO, db_path) == []


def test_hidro_foreign_keys(tmp_path):
    db_path = str(tmp_path / "hidro.db")
    runner.upgrade(DbKind.HIDRO, db_path)
    engine = create_engine(sqlite_url(db_path))
    try:
        inspector = inspect(engine)
        expected = {
            table: {("Estacao", "EstacaoCodigo")}
            for table in (
                "Chuvas", "Cotas", "CurvaDescarga", "Granulometria",
                "PerfilTransversal", "QualAgua", "ResumoDescarga",
                "Sedimentos", "Vazoes", "Telemetria",
            )
        }
        expected.update({
            "SubBacia": {("Bacia", "BaciaCodigo")},
            "Rio": {
                ("Bacia", "BaciaCodigo"),
                ("SubBacia", "SubBaciaCodigo"),
            },
            "Estacao": {
                ("Municipio", "MunicipioCodigo"),
                ("Estado", "EstadoSigla"),
                ("Rio", "RioCodigo"),
                ("SubBacia", "SubBaciaCodigo"),
            },
            "Municipio": {("Estado", "EstadoCodigo")},
        })
        for table, pairs in expected.items():
            actual = {
                (fk["referred_table"], fk["constrained_columns"][0])
                for fk in inspector.get_foreign_keys(table)
            }
            assert actual == pairs

        unique = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("Estado")
        }
        assert ("Sigla",) in unique
        indexes = {
            tuple(item["column_names"])
            for item in inspector.get_indexes("PerfilTransversal")
        }
        assert ("EstacaoCodigo",) in indexes
    finally:
        engine.dispose()


def test_client_upgrade_creates_schema(tmp_path):
    db_path = str(tmp_path / "client.db")

    runner.upgrade(DbKind.CLIENT, db_path)

    assert runner.current(DbKind.CLIENT, db_path) == BASELINE_REVISION
    assert _table_names(db_path) == set(ClientBase.metadata.tables) | {
        "alembic_version"
    }
    assert runner.check(DbKind.CLIENT, db_path) == []


def test_upgrade_is_idempotent(tmp_path):
    db_path = str(tmp_path / "hidro.db")

    runner.upgrade(DbKind.HIDRO, db_path)
    runner.upgrade(DbKind.HIDRO, db_path)

    assert runner.current(DbKind.HIDRO, db_path) == BASELINE_REVISION
    assert runner.check(DbKind.HIDRO, db_path) == []


def test_upgrade_or_raise_creates_schema(tmp_path):
    db_path = str(tmp_path / "client.db")

    runner.upgrade_or_raise(db_path, "client")

    assert runner.current(DbKind.CLIENT, db_path) == BASELINE_REVISION
    assert runner.check(DbKind.CLIENT, db_path) == []


def test_upgrade_refuses_legacy_database(tmp_path):
    db_path = str(tmp_path / "hidro.db")
    engine = create_engine(sqlite_url(db_path))
    HidroBase.metadata.create_all(engine)
    engine.dispose()

    with pytest.raises(runner.LegacyDatabaseError, match="stamp v0.0.0"):
        runner.upgrade(DbKind.HIDRO, db_path)


def test_stamp_legacy_hidro_ignores_unmanaged_tables(tmp_path):
    db_path = str(tmp_path / "hidro.db")
    engine = create_engine(sqlite_url(db_path))
    HidroBase.metadata.create_all(engine)

    legacy = MetaData()
    Table(
        "LegacyHidroExtra",
        legacy,
        Column("RegistroID", Integer, primary_key=True),
    )
    Table("LegacyHidroJobs", legacy, Column("ID", Integer, primary_key=True))
    legacy.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            HidroBase.metadata.tables["Bacia"].insert().values(
                Nome="Test basin",
                Codigo=1,
            )
        )
    engine.dispose()

    assert runner.stamp(DbKind.HIDRO, db_path) == BASELINE_REVISION
    assert runner.current(DbKind.HIDRO, db_path) == BASELINE_REVISION
    assert runner.check(DbKind.HIDRO, db_path) == []

    tables = _table_names(db_path)
    assert "LegacyHidroExtra" in tables
    assert "LegacyHidroJobs" in tables

    engine = create_engine(sqlite_url(db_path))
    try:
        with engine.connect() as connection:
            count = connection.execute(
                select(func.count()).select_from(
                    HidroBase.metadata.tables["Bacia"]
                )
            ).scalar_one()
        assert count == 1
    finally:
        engine.dispose()


def test_stamp_legacy_client_ignores_series_constraint(tmp_path):
    db_path = str(tmp_path / "client.db")
    engine = create_engine(sqlite_url(db_path))
    ClientBase.metadata.create_all(engine)

    legacy = MetaData()
    Table("LegacyClientExtra", legacy, Column("ID", Integer, primary_key=True))
    legacy.create_all(engine)

    Index(
        "uq_series_jobs",
        SeriesJobs.HidroTable,
        SeriesJobs.StationID,
        SeriesJobs.FromDate,
        SeriesJobs.ToDate,
        unique=True,
    ).create(engine)
    engine.dispose()

    assert runner.stamp(DbKind.CLIENT, db_path) == BASELINE_REVISION
    assert runner.current(DbKind.CLIENT, db_path) == BASELINE_REVISION
    assert runner.check(DbKind.CLIENT, db_path) == []
    assert "LegacyClientExtra" in _table_names(db_path)


def test_stamp_rejects_schema_drift(tmp_path):
    db_path = str(tmp_path / "client.db")
    engine = create_engine(sqlite_url(db_path))
    ClientBase.metadata.create_all(
        engine,
        tables=[ClientBase.metadata.tables["Credentials"]],
    )
    engine.dispose()

    with pytest.raises(runner.SchemaDriftError):
        runner.stamp(DbKind.CLIENT, db_path)

    assert runner.current(DbKind.CLIENT, db_path) == "unstamped"


def test_stamp_rejects_already_stamped_database(tmp_path):
    db_path = str(tmp_path / "hidro.db")
    runner.upgrade(DbKind.HIDRO, db_path)

    engine = create_engine(sqlite_url(db_path))
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE alembic_version SET version_num = 'v9.9.9'")
            )
    finally:
        engine.dispose()

    with pytest.raises(runner.MigrationError, match="already stamped at v9.9.9"):
        runner.stamp(DbKind.HIDRO, db_path)


def test_stamp_adopts_empty_version_table(tmp_path):
    db_path = str(tmp_path / "client.db")
    engine = create_engine(sqlite_url(db_path))
    ClientBase.metadata.create_all(engine)
    Table(
        "alembic_version",
        MetaData(),
        Column("version_num", String(32), primary_key=True),
    ).create(engine)
    engine.dispose()

    assert runner.stamp(DbKind.CLIENT, db_path) == BASELINE_REVISION
    assert runner.current(DbKind.CLIENT, db_path) == BASELINE_REVISION


def test_stamp_rejects_empty_database(tmp_path):
    db_path = tmp_path / "client.db"
    Path(db_path).touch()

    with pytest.raises(runner.MigrationError, match="empty"):
        runner.stamp(DbKind.CLIENT, str(db_path))


def test_check_requires_stamped_database(tmp_path):
    db_path = str(tmp_path / "client.db")
    engine = create_engine(sqlite_url(db_path))
    ClientBase.metadata.create_all(engine)
    engine.dispose()

    with pytest.raises(runner.LegacyDatabaseError, match="stamp v0.0.0"):
        runner.check(DbKind.CLIENT, db_path)


def test_current_reports_missing_and_unstamped(tmp_path):
    missing = str(tmp_path / "missing.db")
    assert runner.current(DbKind.HIDRO, missing) == "missing"

    unstamped = str(tmp_path / "unstamped.db")
    engine = create_engine(sqlite_url(unstamped))
    HidroBase.metadata.create_all(engine)
    engine.dispose()
    assert runner.current(DbKind.HIDRO, unstamped) == "unstamped"


def test_history_and_heads_return_baseline():
    for kind in (DbKind.HIDRO, DbKind.CLIENT):
        revisions = runner.history(kind)

        assert [revision.revision for revision in revisions] == [BASELINE_REVISION]
        assert revisions[0].down_revision is None
        assert runner.heads(kind) == (BASELINE_REVISION,)


def test_init_db_creates_both_schemas(tmp_path):
    hidro_path = str(tmp_path / "hidro.db")
    client_path = str(tmp_path / "client.db")

    init_db(hidro_path, client_path)

    assert runner.current(DbKind.HIDRO, hidro_path) == BASELINE_REVISION
    assert runner.current(DbKind.CLIENT, client_path) == BASELINE_REVISION


def test_init_db_rejects_unstamped_hidro(tmp_path):
    hidro_path = str(tmp_path / "hidro.db")
    client_path = str(tmp_path / "client.db")
    engine = create_engine(sqlite_url(hidro_path))
    HidroBase.metadata.create_all(engine)
    engine.dispose()

    with pytest.raises(runner.LegacyDatabaseError, match="stamp v0.0.0"):
        init_db(hidro_path, client_path)


def test_cli_upgrade_current_check_and_history(tmp_path, capsys):
    db_path = str(tmp_path / "hidro.db")

    assert cli.main(["--hidro", db_path, "hidro", "upgrade"]) == 0
    assert cli.main(["--hidro", db_path, "hidro", "current"]) == 0
    assert cli.main(["--hidro", db_path, "hidro", "check"]) == 0
    assert cli.main(["--hidro", db_path, "hidro", "heads"]) == 0
    assert cli.main(["--hidro", db_path, "hidro", "history"]) == 0

    output = capsys.readouterr().out
    assert "v0.0.0" in output
    assert "ok" in output
    assert "initial schema" in output


def test_cli_all_upgrade_and_current(tmp_path, capsys):
    hidro_path = str(tmp_path / "hidro.db")
    client_path = str(tmp_path / "client.db")

    assert (
        cli.main(
            [
                "--hidro",
                hidro_path,
                "--client",
                client_path,
                "all",
                "upgrade",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "--hidro",
                hidro_path,
                "--client",
                client_path,
                "all",
                "current",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert f"hidro: {BASELINE_REVISION}" in output
    assert f"client: {BASELINE_REVISION}" in output


def test_cli_stamp_is_idempotent(tmp_path, capsys):
    db_path = str(tmp_path / "hidro.db")
    engine = create_engine(sqlite_url(db_path))
    HidroBase.metadata.create_all(engine)
    engine.dispose()

    assert cli.main(["--hidro", db_path, "hidro", "stamp", "v0.0.0"]) == 0
    assert cli.main(["--hidro", db_path, "hidro", "stamp", "v0.0.0"]) == 0
    assert runner.current(DbKind.HIDRO, db_path) == BASELINE_REVISION

    output = capsys.readouterr().out
    assert output.count("stamped v0.0.0") == 2


def test_cli_reports_missing_database(tmp_path, capsys):
    db_path = str(tmp_path / "missing.db")

    assert cli.main(["--hidro", db_path, "hidro", "stamp", "v0.0.0"]) == 1
    assert cli.main(["--hidro", db_path, "hidro", "check"]) == 1

    error = capsys.readouterr().err
    assert "does not exist" in error


def test_main_reports_migration_error_without_traceback():
    import hidrocli.__main__ as entry

    with (
        patch("hidrocli.config.parse_config"),
        patch("hidrocli.config.setup_logger"),
        patch(
            "hidrocli.config.setup_database",
            side_effect=runner.LegacyDatabaseError("stamp v0.0.0"),
        ),
    ):
        with pytest.raises(SystemExit, match="stamp v0.0.0"):
            entry.cli()

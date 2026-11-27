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

"""Startup and runtime diagnostics for the SQLite databases.

The checks are intentionally tiered: cheap metadata and pragma inspection at
``TRACE``, data checks on small tables at ``DEBUG``, and full scans at
``VERBOSE``. Runtime DBAPI errors are always logged at warning level.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import event

from hidro_orm.runner import check
from hidro_orm.schema import DbKind

logger = logging.getLogger(__name__)

TRACE = 15
"""Cheap diagnostics level, matching the project's TRACE logger."""

VERBOSE = 5
"""Full-scan diagnostics level, matching the project's VERBOSE logger."""

SLOW_QUERY_SECONDS = 1.0
"""Minimum statement duration logged at VERBOSE."""

_SERIES_TABLES = (
    "Chuvas", "Cotas", "CurvaDescarga", "Granulometria", "PerfilTransversal",
    "QualAgua", "ResumoDescarga", "Sedimentos", "Vazoes",
)

_SMALL_ORPHANS = (
    (
        "Rio.SubBaciaCodigo -> SubBacia",
        "SELECT count(*) FROM Rio r WHERE r.SubBaciaCodigo IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM SubBacia s WHERE s.Codigo = r.SubBaciaCodigo)",
    ),
    (
        "Municipio.EstadoCodigo -> Estado",
        "SELECT count(*) FROM Municipio m WHERE m.EstadoCodigo IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM Estado e WHERE e.Codigo = m.EstadoCodigo)",
    ),
    (
        "Estacao.MunicipioCodigo -> Municipio",
        "SELECT count(*) FROM Estacao s WHERE s.MunicipioCodigo IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM Municipio m WHERE m.Codigo = s.MunicipioCodigo)",
    ),
    (
        "Estacao.RioCodigo -> Rio",
        "SELECT count(*) FROM Estacao s WHERE s.RioCodigo IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM Rio r WHERE r.Codigo = s.RioCodigo)",
    ),
    (
        "Estacao.SubBaciaCodigo -> SubBacia",
        "SELECT count(*) FROM Estacao s WHERE s.SubBaciaCodigo IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM SubBacia b WHERE b.Codigo = s.SubBaciaCodigo)",
    ),
    (
        "Estacao.EstadoSigla -> Estado",
        "SELECT count(*) FROM Estacao s WHERE s.EstadoSigla IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM Estado e WHERE e.Sigla = s.EstadoSigla)",
    ),
) + tuple(
    (
        f"{table}.EstacaoCodigo -> Estacao",
        f'SELECT count(*) FROM "{table}" t WHERE t.EstacaoCodigo IS NOT NULL '
        "AND NOT EXISTS (SELECT 1 FROM Estacao e WHERE e.Codigo = t.EstacaoCodigo)",
    )
    for table in _SERIES_TABLES
)

_JOB_RECORD_TABLES = (
    ("BaseJobs", (
        "Bacia", "SubBacia", "Entidade", "Municipio", "Rio", "Estado",
    )),
    ("StationJobs", ("Estacao",)),
    ("SeriesJobs", _SERIES_TABLES),
    ("TelemetryJobs", ("Telemetria",)),
)


def _statement(statement: str) -> str:
    """Return a compact, parameter-free statement for logging."""

    return " ".join(str(statement).split())[:500]


def install_database_hooks(engine, label: str) -> None:
    """Install SQLAlchemy hooks for DBAPI errors and slow statements."""

    @event.listens_for(engine, "handle_error")
    def _log_dbapi_error(context):
        error = getattr(context, "original_exception", None)
        if error is None:
            return
        detail = str(error.args[0]) if error.args else type(error).__name__
        logger.warning(
            f"[DB {label}] {type(error).__name__}: {detail}; "
            f"sql={_statement(context.statement or '')}"
        )

    @event.listens_for(engine, "before_cursor_execute")
    def _start_timer(conn, cursor, statement, parameters, context, executemany):
        conn.info["_diag_start"] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _log_slow_query(conn, cursor, statement, parameters, context, executemany):
        started = conn.info.pop("_diag_start", None)
        if started is None or not logger.isEnabledFor(VERBOSE):
            return
        elapsed = time.perf_counter() - started
        if elapsed >= SLOW_QUERY_SECONDS:
            logger.log(
                VERBOSE,
                f"[DB {label}] slow query {elapsed:.3f}s: {_statement(statement)}",
            )


def log_database_diagnostics(kind: DbKind | str, db_path, database) -> None:
    """Run the tiered diagnostics for one database connection."""

    if not logger.isEnabledFor(TRACE):
        return

    kind = DbKind(kind)
    label = database.type.value
    try:
        with database.engine.connect() as connection:
            _log_pragmas(connection, label)
            _log_schema(kind, db_path, label)
            if logger.isEnabledFor(logging.DEBUG):
                _log_deep(connection, label, kind)
            if logger.isEnabledFor(VERBOSE):
                _log_full(connection, label, kind)
    except Exception as exc:
        logger.log(TRACE, f"[DB {label}] diagnostics failed: {exc}")


def _log_pragmas(connection, label: str) -> None:
    pragmas = (
        ("foreign_keys", "PRAGMA foreign_keys"),
        ("journal_mode", "PRAGMA journal_mode"),
        ("synchronous", "PRAGMA synchronous"),
        ("busy_timeout", "PRAGMA busy_timeout"),
        ("cache_size", "PRAGMA cache_size"),
        ("page_count", "PRAGMA page_count"),
        ("freelist_count", "PRAGMA freelist_count"),
    )
    for name, sql in pragmas:
        try:
            value = connection.exec_driver_sql(sql).scalar()
        except Exception as exc:
            logger.log(TRACE, f"[DB {label}] pragma {name} failed: {exc}")
            continue
        logger.log(TRACE, f"[DB {label}] {name}={value}")

    try:
        version = connection.exec_driver_sql("SELECT sqlite_version()").scalar()
        options = [
            row[0] for row in
            connection.exec_driver_sql("PRAGMA compile_options").fetchall()
        ]
        logger.log(TRACE, f"[DB {label}] sqlite={version} compile={','.join(options)}")
    except Exception as exc:
        logger.log(TRACE, f"[DB {label}] sqlite version/options failed: {exc}")


def _log_schema(kind: DbKind, db_path, label: str) -> None:
    try:
        differences = check(kind, db_path)
    except Exception as exc:
        logger.log(TRACE, f"[DB {label}] schema check failed: {exc}")
        return

    if not differences:
        logger.log(TRACE, f"[DB {label}] schema matches metadata")
        return

    logger.warning(
        f"[DB {label}] schema drift: {len(differences)} difference(s)"
    )
    for difference in differences[:20]:
        logger.log(logging.DEBUG, f"[DB {label}] drift: {difference}")


def _query_count(connection, sql: str, label: str, description: str):
    try:
        return connection.exec_driver_sql(sql).scalar()
    except Exception as exc:
        logger.log(logging.DEBUG, f"[DB {label}] {description} skipped: {exc}")
        return None


def _log_deep(connection, label: str, kind: DbKind) -> None:
    logger.log(logging.DEBUG, f"[DB {label}] running quick_check")
    try:
        result = connection.exec_driver_sql("PRAGMA quick_check").fetchall()
        if result == [("ok",)]:
            logger.log(logging.DEBUG, f"[DB {label}] quick_check=ok")
        else:
            logger.warning(f"[DB {label}] quick_check: {result[:5]}")
    except Exception as exc:
        logger.log(logging.DEBUG, f"[DB {label}] quick_check failed: {exc}")

    try:
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if violations:
            logger.warning(
                f"[DB {label}] foreign_key_check: {len(violations)} violation(s)"
            )
            for row in violations[:10]:
                logger.warning(f"[DB {label}] foreign key violation: {row}")
        else:
            logger.log(logging.DEBUG, f"[DB {label}] foreign_key_check=ok")
    except Exception as exc:
        logger.log(logging.DEBUG, f"[DB {label}] foreign_key_check failed: {exc}")

    if kind is not DbKind.HIDRO:
        return
    for description, sql in _SMALL_ORPHANS:
        count = _query_count(connection, sql, label, description)
        if count:
            logger.warning(f"[DB {label}] {description}: {count} orphan(s)")
        elif count == 0:
            logger.log(logging.DEBUG, f"[DB {label}] {description}: 0")


def _log_full(connection, label: str, kind: DbKind) -> None:
    logger.log(VERBOSE, f"[DB {label}] running integrity_check")
    try:
        result = connection.exec_driver_sql("PRAGMA integrity_check").fetchall()
        if result == [("ok",)]:
            logger.log(VERBOSE, f"[DB {label}] integrity_check=ok")
        else:
            logger.warning(f"[DB {label}] integrity_check: {result[:5]}")
    except Exception as exc:
        logger.log(VERBOSE, f"[DB {label}] integrity_check failed: {exc}")

    if kind is DbKind.HIDRO:
        count = _query_count(
            connection,
            "SELECT count(*) FROM Telemetria t WHERE t.EstacaoCodigo IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM Estacao e WHERE e.Codigo = t.EstacaoCodigo)",
            label,
            "Telemetria.EstacaoCodigo -> Estacao",
        )
        if count:
            logger.warning(f"[DB {label}] Telemetria orphan EstacaoCodigo: {count}")
        elif count == 0:
            logger.log(VERBOSE, f"[DB {label}] Telemetria orphan EstacaoCodigo: 0")

    if kind is not DbKind.CLIENT:
        return
    for table, names in _JOB_RECORD_TABLES:
        quoted = ", ".join(f"'{name}'" for name in names)
        sql = (
            "SELECT count(*) FROM JobRecords jr "
            f"WHERE jr.JobName IN ({quoted}) AND NOT EXISTS "
            f"(SELECT 1 FROM {table} j WHERE j.ID = jr.JobID)"
        )
        count = _query_count(connection, sql, label, f"JobRecords -> {table}")
        if count:
            logger.warning(f"[DB {label}] JobRecords -> {table}: {count} orphan(s)")
        elif count == 0:
            logger.log(VERBOSE, f"[DB {label}] JobRecords -> {table}: 0")

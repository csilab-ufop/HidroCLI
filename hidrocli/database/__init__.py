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

from sqlalchemy     import create_engine, UniqueConstraint
from sqlalchemy.orm import sessionmaker, Session

from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from hidrocli.models.client import (
    BaseJobs, StationJobs, SeriesJobs, TelemetryJobs, HidroJob, Token, JobStatus,
    BaseTables, SeriesTables, TelemetryTables,
)
from hidrocli.models.hidro import (
    HidroBase, Basin, SubBasin, Entity, Township, River, State, Station,
    Rain, DischargeMeasurement, Sediments, Stage, RatingCurve,
    WaterQuality, WaterQualityStatus, Granulometry, CrossSection,
    VerticalCrossSection, FlowRate, Telemetry,
)

class DatabaseType(StrEnum):
    """
    Enum to name databases
    """

    HIDRO  = "Hidro"
    CLIENT = "Client"

class DatabaseConnection:
    """ Class to hold database engine."""

    def __init__(self, dbq: str, db_type: DatabaseType):
        self.engine  = create_engine(f"sqlite:///{dbq}", echo=False)
        self.Session = sessionmaker(bind=self.engine)
        self.type    = db_type

    def get_session(self) -> Session:
        return self.Session()
    def close(self):
        self.engine.dispose()


def _ensure_db_directory(db_path: str) -> None:
    """ Create the parent directory of a database path if it is missing."""

    Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _setup_db(db_path, db_type) -> DatabaseConnection:
    """ Setup a DatabaseConnection and bring its schema to the latest revision."""

    _ensure_db_directory(db_path)
    db = DatabaseConnection(db_path, db_type)

    from hidro_orm.runner import upgrade_or_raise

    try:
        upgrade_or_raise(db_path, db_type.value.lower())
    except Exception:
        db.close()
        raise

    return db


def init_db(hidro_path, client_path) -> None:
    """ Init an DatabaseConnection"""

    import hidrocli.database.hidro  as hidro
    import hidrocli.database.client as client

    hidro.HIDRO_DB   = _setup_db(hidro_path, DatabaseType.HIDRO)
    client.CLIENT_DB = _setup_db(client_path, DatabaseType.CLIENT)


# ---------------------------------------------------------------------------
# Model metadata.
#
# The database layer is the only place that knows the ORM models: it maps a job
# name to its Hidro model and client job-queue model, and describes each model's
# upsert identity and station observation period. The job-level registry in
# ``hidrocli.jobs`` receives this metadata from here.
# ---------------------------------------------------------------------------

_HIDRO_BY_TABLE = {
    mapper.class_.__tablename__: mapper.class_
    for mapper in HidroBase.registry.mappers
}


_BASE_NAMES      = {table.value for table in BaseTables}
_SERIES_NAMES    = {table.value for table in SeriesTables}
_TELEMETRY_NAMES = {table.value for table in TelemetryTables}

def get_hidro_model(name: str):
    """Return the Hidro ORM model for a job/table name."""
    return _HIDRO_BY_TABLE[name]


def get_job_model(name: str):
    """Return the Client job-queue model for a job name (or ``None``)."""
    if name == BaseTables.STATION:
        return StationJobs
    if name in _BASE_NAMES:
        return BaseJobs
    if name in _SERIES_NAMES:
        return SeriesJobs
    if name in _TELEMETRY_NAMES:
        return TelemetryJobs
    return None


def unique_keys(name: str) -> tuple:
    """Return a job's row identity from the ORM constraints.

    Uses the unique constraint (ignoring the ``DataAlt`` audit column) or, when
    there is none, the foreign key columns.
    """
    table = get_hidro_model(name).__table__
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            return tuple(c.name for c in constraint.columns if c.name != "DataAlt")
    return tuple(c.name for c in table.columns if c.foreign_keys)


def get_verify_keys(name: str) -> dict:
    """Return the upsert identity as ``{attribute: attribute}``."""
    return {attr: attr for attr in unique_keys(name)}


def get_station_period(name: str):
    """Return the ``(start, end)`` ``Station`` attribute names for a series job."""
    return get_hidro_model(name).__table__.info.get("station_period")


def get_field_names(name: str) -> list:
    """Return the attribute names mapped from a job's ANA payload."""
    model = get_hidro_model(name)
    return [col.key for col in model.__table__.columns if "ana" in col.info]


def job_names() -> list:
    """Return every known job/table name."""
    return list(_HIDRO_BY_TABLE)

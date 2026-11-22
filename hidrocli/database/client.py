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

from datetime import datetime

from sqlalchemy                  import func
from sqlalchemy.dialects.sqlite  import insert as sqlite_insert
from sqlalchemy.sql              import elements

from typing import List

from hidrocli.models.client import *

CLIENT_DB   = None

JOB_RECORD_CHUNK = 4_000
"""Maximum mapping rows written by one SQLite upsert statement."""

def count_client(model: ClientBase):
    """ Counts a given Model in Client Database. """

    client_session = CLIENT_DB.get_session()
    count_model    = client_session.query(model).count()
    client_session.close()
    return count_model


def insert_credentials(user_id, password):
    """ Insert an Credentials model entrie in Client Database. """

    credentials = Credentials(ID=user_id, Password=password)
    client_session = CLIENT_DB.get_session()
    client_session.add(credentials)
    client_session.commit()
    client_session.close()


def check_credentials():
    return count_client(Credentials)


def get_credentials() -> Credentials:
    """ Gets the first registered Credential on Client Database and returns it. """

    client_session = CLIENT_DB.get_session()
    credentials    = client_session.query(Credentials).first()
    client_session.close()
    return credentials


def get_token_model() -> Token:
    """ Returns the first found Token on Client Database """

    client_session = CLIENT_DB.get_session()
    token          = client_session.query(Token).first()
    client_session.close()
    return token


def add_token(client_id, token, expires):
    """ Add an Token to Client Database """

    client_session = CLIENT_DB.get_session()
    client_session.add(Token(CredentialID=client_id, Token=token, Expires=expires))
    client_session.commit()
    client_session.close()


def update_token(RegistroID, new_token, new_expires):
    """ Updates an Token on Client Database """

    client_session = CLIENT_DB.get_session()
    from sqlalchemy import update;
    update_expression = (
        update(Token).where(Token.RegistroID == RegistroID)
        .values(Token=new_token, Expires=new_expires)
    )
    client_session.execute(update_expression)
    client_session.commit()
    client_session.close()


def upsert_job_records(records: List[dict]) -> int:
    """Insert or refresh the data-row mappings produced by jobs.

    The unique key is ``(DataTable, DataID)``. Re-running a job updates the
    mapping to point at the latest job instead of creating a duplicate.
    Records without a job identifier or data identifier are ignored.
    """

    if not records:
        return 0

    now     = datetime.now()
    pending = {}
    for record in records:
        job_id  = record.get("JobID")
        data_id = record.get("DataID")
        if job_id is None or data_id is None:
            continue
        key = (record["DataTable"], data_id)
        pending[key] = {
            "JobID":     job_id,
            "JobName":   record["JobName"],
            "DataTable": record["DataTable"],
            "DataID":    data_id,
            "DataIns":   record.get("DataIns", now),
        }

    values = list(pending.values())
    if not values:
        return 0

    client_session = CLIENT_DB.get_session()
    try:
        for start in range(0, len(values), JOB_RECORD_CHUNK):
            chunk     = values[start:start + JOB_RECORD_CHUNK]
            statement = sqlite_insert(JobRecords).values(chunk)
            statement = statement.on_conflict_do_update(
                index_elements=[JobRecords.DataTable, JobRecords.DataID],
                set_={
                    "JobID":   statement.excluded.JobID,
                    "JobName": statement.excluded.JobName,
                    "DataAlt": now,
                },
            )
            client_session.execute(statement)
        client_session.commit()
    finally:
        client_session.close()
    return len(values)


def get_job_model(name: str):
    """Return the Client job-queue model for a job name (from the registry)."""
    from hidrocli.database import get_job_model as _registry_job_model
    return _registry_job_model(name)


def create_job_filters(job_name: str, status: List[int], last_check: bool,
                       stations=[], max_retries=False,
                       initial_date=None, final_date=None) -> List[elements]:
    """Build filters for a job table.

    ``initial_date`` and ``final_date`` restrict series jobs to windows fully
    contained in the requested interval, so legacy jobs outside it are not
    queued for the current run.
    """

    model   = get_job_model(job_name)
    filters = [model.HidroTable == job_name]
    if stations:
        filters.append(model.StationID.in_(stations))
    if max_retries:
        filters.append(model.Retries < 3)
    if initial_date is not None:
        filters.append(model.FromDate >= initial_date)
    if final_date is not None:
        filters.append(model.ToDate <= final_date)
    if status or last_check:
        sub_filters = []
        if status:
            sub_filters.append(model.Status.in_(status))
        if last_check:
            from datetime import date
            sub_filters.append(model.LastCheck < date.today())
        if sub_filters:
            from sqlalchemy import or_
            filters.append(or_(*sub_filters))
    return filters

    
def count_job(job_name: str, filters: List[elements]) -> int:
    """ Counts jobs registered in Client Database. """

    client_session = CLIENT_DB.get_session()
    model          = get_job_model(job_name)
    count_job      = client_session.query(model).filter(*filters).count()
    client_session.close()
    return count_job


def count_job_by_status(job_name: str):

    client_session = CLIENT_DB.get_session()
    model          = get_job_model(job_name)
    count_jobs     = (client_session.query(model.Status, func.count(model.ID).label('count'))
                      .filter(model.HidroTable == job_name, model.Status != JobStatus.CORRUPTED.value)
                      .group_by(model.Status).order_by(model.Status).all())
    client_session.close()
    return count_jobs


def get_station_ids(job_name: str, stations=()) -> set:
    """ Return the station IDs that already have a job for ``job_name``. """

    client_session = CLIENT_DB.get_session()
    model          = get_job_model(job_name)
    query          = client_session.query(model.StationID).filter(
        model.HidroTable == job_name
    )
    if stations:
        query = query.filter(model.StationID.in_(stations))
    station_ids = {row[0] for row in query.distinct()}
    client_session.close()
    return station_ids


def insert_jobs(jobs: List[HidroJob]) -> None:
    """ Insert a list of Jobs into Client Database. """

    client_session = CLIENT_DB.get_session()
    client_session.add_all(jobs)
    client_session.commit()
    client_session.close()


def make_series_job(station_id, from_date, to_date, status, hidro_table):
    """Build a series job instance for a station/time window."""

    return SeriesJobs(
        StationID  = station_id,
        FromDate   = from_date,
        ToDate     = to_date,
        Status     = status,
        HidroTable = hidro_table,
    )


def update_jobs(jobs: List[HidroJob], job_name: str) -> None:
    """ Updates a list of Jobs. """

    client_session = CLIENT_DB.get_session()
    client_session.bulk_update_mappings(get_job_model(job_name), jobs)
    client_session.commit()
    client_session.close()


def iter_jobs(job_name: str, filters: List[elements], chunk_size: int = 1000):
    """Yield jobs in bounded keyset pages.

    Only ``chunk_size`` ORM instances are alive at a time, so scheduling a
    table with millions of rows no longer hydrates the whole queue. Instances
    are detached before the session closes so callers can enqueue and mutate
    them safely.
    """

    model      = get_job_model(job_name)
    chunk_size = max(1, chunk_size)
    last_id    = 0

    while True:
        client_session = CLIENT_DB.get_session()
        try:
            chunk = (
                client_session.query(model)
                .filter(*filters, model.ID > last_id)
                .order_by(model.ID)
                .limit(chunk_size)
                .all()
            )
            for job in chunk:
                client_session.expunge(job)
            last_id = chunk[-1].ID if chunk else 0
        finally:
            client_session.close()

        if not chunk:
            return
        yield from chunk


def job_to_mapping(job: HidroJob) -> dict:
    """Return a bulk-insert mapping for an unsaved job instance.

    Bulk mappings bypass the ORM flush, so unset columns are filled from their
    Python-side defaults here (for example ``Retries`` and ``LastCheck``).
    """

    mapping = dict(job)
    mapping.pop("ID", None)

    for key, value in list(mapping.items()):
        if value is not None:
            continue
        column  = job.__table__.columns.get(key)
        default = column.default if column is not None else None
        if default is None:
            continue
        mapping[key] = default.arg(None) if default.is_callable else default.arg
    return mapping


def insert_jobs_bulk(jobs: List[HidroJob]) -> None:
    """Insert jobs with ORM bulk mappings, bypassing the identity map."""

    if not jobs:
        return
    insert_job_mappings(jobs[0].HidroTable, [job_to_mapping(job) for job in jobs])


def insert_job_mappings(job_name: str, mappings: List[dict]) -> None:
    """Insert a chunk of job mappings without creating ORM instances."""

    if not mappings:
        return

    model          = get_job_model(job_name)
    client_session = CLIENT_DB.get_session()
    try:
        client_session.bulk_insert_mappings(model, mappings)
        client_session.commit()
    finally:
        client_session.close()


def update_job_mappings(job_name: str, mappings: List[dict]) -> None:
    """Update a chunk of job mappings; every mapping needs its primary key."""

    if not mappings:
        return

    model          = get_job_model(job_name)
    client_session = CLIENT_DB.get_session()
    try:
        client_session.bulk_update_mappings(model, mappings)
        client_session.commit()
    finally:
        client_session.close()


def reset_series_job_dates(job_name: str, station_ids, to_date,
                           chunk_size: int = 1000) -> int:
    """Reset stale yearly series jobs to ``to_date`` with ORM bulk updates."""

    station_ids = list(station_ids)
    if not station_ids:
        return 0

    updated    = 0
    chunk_size = max(1, chunk_size)

    for start in range(0, len(station_ids), chunk_size):
        chunk          = station_ids[start:start + chunk_size]
        client_session = CLIENT_DB.get_session()
        try:
            updated += client_session.query(SeriesJobs).filter(
                SeriesJobs.HidroTable == job_name,
                SeriesJobs.StationID.in_(chunk),
                SeriesJobs.Status != JobStatus.CORRUPTED.value,
                SeriesJobs.ToDate < to_date,
                (func.julianday(SeriesJobs.ToDate)
                 - func.julianday(SeriesJobs.FromDate)) < 365,
            ).update({
                SeriesJobs.Status: JobStatus.PENDING.value,
                SeriesJobs.ToDate: to_date,
            }, synchronize_session=False)
            client_session.commit()
        finally:
            client_session.close()
    return updated

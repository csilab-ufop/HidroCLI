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

"""
Provides routines to request and sync data on database.
"""

import logging, time, json
logger = logging.getLogger(__name__)

from concurrent.futures import (
    ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED,
)
from threading          import Thread, Lock
from queue              import Queue

from datetime    import datetime, timedelta, date
from enum        import Enum, auto, StrEnum
from dataclasses import dataclass

from hidrocli.database.client import *
from hidrocli.database.hidro  import *

from hidrocli.webservices import *

MAX_WORKERS      = None
"""Maximum number of worker threads used for parallel requests."""

BATCH_SIZE       = None
"""Number of accumulated records or jobs that triggers a database write."""

SKIP_SERIES_JOBS = False
"""Skip every series job when true."""

SKIP_FOR         = []
"""Series jobs to skip, by name."""

RUN_FOR          = []
"""Series jobs to run; empty means every job not skipped."""

STATIONS         = []
"""Station codes used to restrict series jobs; empty means every station."""

FILTER           = "DATA_ULTIMA_ATUALIZACAO"
"""Date field used to filter ANA series requests."""

INITIAL_DATE     = None
"""Optional initial date override for series jobs."""

FINAL_DATE       = None
"""Optional final date override for series jobs."""

SAVE_JSON        = False
"""Save raw API responses as JSON files."""

READ_JSON        = False
"""Reuse cached JSON responses instead of requesting the API."""

JSON_DIR         = "json"
"""Directory used for cached JSON payloads."""


JOB_CHUNK_SIZE = 5000
"""Minimum number of jobs to accumulate before one bulk insert."""


class JobConfig:
    """ Hold basic config data for jobs. """

    class Base(StrEnum):
        """ Enum to hold basic resources data that does not require Threads. """

        BASIN     = "Bacia"
        SUB_BASIN = "SubBacia"
        ENTITY    = "Entidade"
        TOWNSHIP  = "Municipio"
        RIVER     = "Rio"
        STATE     = "Estado"
        STATION   = "Estacao"

    class Series(StrEnum):
        """ Enum to hold Hidro Jobs that will run with threads. """

        RAIN              = "Chuvas"
        DISCHARGE_SUMMARY = "ResumoDescarga"
        SEDIMENTS         = "Sedimentos"
        FLOW_RATE         = "Vazoes"
        GRANULOMETRY      = "Granulometria"
        DISCHARGE_FLOW    = "CurvaDescarga"
        WATER_QUALITY     = "QualAgua"
        CROSS_SECTION     = "PerfilTransversal"
        STAGE             = "Cotas"

    class Status(Enum):
        """ Enum to hold the result status of a job. """

        PENDING   = auto()
        FAILED    = auto()
        INVALID   = auto()
        CORRUPTED = auto()
        COMPLETED = auto()


@dataclass
class SerieStationData:
    """ Data class to receive Series Job data when starting a job."""

    station_code: int
    """ Station code which data will be requested."""

    start_date: DateTime
    """ Start date which data will be requested"""

    end_date: DateTime
    """ End date which data will be requested"""

    def __iter__(self):
        return iter((self.station_code, self.start_date, self.end_date))


@dataclass
class QueueData:
    """ Data class to hold expected interface data by writer thread."""

    job_config:  JobConfig
    job:         HidroJob
    items:       dict
    worker_time: float
    stop_signal: bool

    def __iter__(self):
        return iter((
            self.job_config,
            self.job,
            self.items,
            self.worker_time,
            self.stop_signal
        ))


def _batch_size() -> int:
    """Return the configured write/job chunk size, with a safe default."""

    return max(1, BATCH_SIZE or 1000)


def _chunked(items, size: int):
    """Yield ``items`` in lists of at most ``size`` entries."""

    size = max(1, size)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _yesterday() -> datetime:
    """Return yesterday at midnight."""

    return (datetime.now() - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _as_datetime(value):
    """Normalize a database or command-line date, leaving unknown values."""

    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return value


from typing import Optional
_token_cache: Optional[Token] = None
"""Private Token global to control expiration time."""

def get_token() -> Token.Token:
    """Authenticate and return access token.
    
    :returns: Valid token for requesition
    """

    global _token_cache
    if _token_cache is None:
        _token_cache = get_token_model()

    if _token_cache is not None and datetime.now() < _token_cache.Expires:
        logger.verbose(f"Token is valid. ({_token_cache.Expires})")
        return _token_cache.Token

    logger.info("No valid token present, requesting.")
    credentials = get_credentials()
    token, expires = request_token(credentials.ID, credentials.Password)
    if _token_cache is None:
        _token_cache = Token()
    _token_cache.Token   = token
    _token_cache.Expires = expires

    if count_client(Token):
        update_token(_token_cache.RegistroID, token, expires)
    else:
        add_token(credentials.ID, token, expires)

    logger.info("Token acquired and cached.")
    return token


def check_base_job(job_config: JobConfig.Base) -> None:
    """Checks each HidroJob and request/update them.

    :param job: Current Job to check, insert and update.
    :returns: Nothing.
    """

    filters = create_job_filters(job_config, None, last_check=False)
    if not count_job(job_config, filters):
        logger.info(f"Creating jobs for {job_config}.")
        job_model = get_job_model(job_config)
        jobs = []
        match job_config:
            case JobConfig.Base.STATION:
                for state in get_states():
                    job = job_model(
                        HidroTable = job_config,
                        Status     = JobConfig.Status.PENDING.value,
                        UF         = state.Sigla
                    )
                    jobs.append(job)
            case _:
                job = job_model(
                    HidroTable = job_config,
                    Status     = JobConfig.Status.PENDING.value
                )
                jobs.append(job)
        insert_jobs(jobs)
        check_base_job(job_config)
    else:
        status  = [JobConfig.Status.FAILED.value, JobConfig.Status.PENDING.value]
        filters = create_job_filters(job_config, status, last_check=True)
        count   = count_job(job_config, filters)
        if count:
            logger.info(f"Initiating jobs for {job_config}")
            trigger_job(job_config, filters)
            check_base_job(job_config)
        else:
            logger.info(f"No pending jobs for {job_config}.")


def check_series_job(job_config: JobConfig) -> None:
    """Checks an JobConfig.
    Create missing station jobs and start pending jobs requisition.
    """

    selected    = set(STATIONS)
    period_data = []
    for data in get_period(job_config).all():
        if selected and data[0] not in selected:
            continue
        start = INITIAL_DATE if INITIAL_DATE is not None else data[1]
        end   = FINAL_DATE   if FINAL_DATE   is not None else data[2]
        period_data.append((data[0], _as_datetime(start), _as_datetime(end)))

    if selected:
        missing_stations = selected - {data[0] for data in period_data}
        if missing_stations:
            logger.warning(
                f"No period data for stations {sorted(missing_stations)} "
                f"in {job_config}."
            )

    existing = get_station_ids(job_config, STATIONS)
    missing  = [data for data in period_data if data[0] not in existing]
    if missing:
        logger.info(f"Creating jobs from {len(missing)} stations for {job_config}")
        create_series_jobs(missing, job_config)

    if INITIAL_DATE is not None or FINAL_DATE is not None:
        update_series_job_windows(
            job_config,
            [data for data in period_data if data[0] in existing],
        )

    if FINAL_DATE is None:
        update_series_job(job_config)
    trigger_series_jobs(job_config)


def trigger_series_jobs(job_config: JobConfig) -> None:
    """Trigger pending and failed jobs, retrying within the same run."""

    status = [JobConfig.Status.FAILED.value, JobConfig.Status.PENDING.value]
    filters = create_job_filters(job_config, status, last_check=False,
                                 stations=STATIONS, max_retries=True,
                                 initial_date=INITIAL_DATE,
                                 final_date=FINAL_DATE)
    count = count_job(job_config, filters)
    if count:
        logger.info(f"Initiating {count} jobs for {job_config}")
        trigger_job(job_config, filters)
        trigger_series_jobs(job_config)
    else:
        logger.info(f"No pending jobs for {job_config}.")


def create_series_jobs(stations_data: List[SerieStationData], job_config: JobConfig) -> None:
    """ Creates Series Jobs for each SerieStationData received for a given JobConfig.
    Preprocess all years from "Start Date" to "End Date" that will become a job request.
    Jobs are written in bounded chunks to keep memory flat.
    """
    start      = time.time()
    chunk_size = max(_batch_size(), JOB_CHUNK_SIZE)
    workers    = max(1, MAX_WORKERS or 1)
    batch      = []
    created    = 0

    def collect(future):
        nonlocal created
        try:
            processed_jobs = future.result()
        except Exception as e:
            logger.error(f"Error processing period: {e}")
            return
        batch.extend(processed_jobs)
        if len(batch) >= chunk_size:
            insert_jobs_bulk(batch)
            created += len(batch)
            batch.clear()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = set()
        for data in stations_data:
            pending.add(executor.submit(process_period, *data, job_config))
            if len(pending) >= 2 * workers:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    collect(future)
        for future in as_completed(pending):
            collect(future)

    if batch:
        insert_jobs_bulk(batch)
        created += len(batch)

    elapsed = time.time() - start
    logger.info(f"Created {created} jobs for {job_config} in {elapsed:.2f} seconds")


def process_period(station_code, start_date, end_date, job_config):
    """ Creates Series Jobs for each SerieStationData received for a given JobConfig.
    Preprocess all years from "Start Date" to "End Date" that will become a job request.
    """

    start_date = _as_datetime(start_date)
    end_date   = _as_datetime(end_date)
    if end_date is None:
        end_date = _yesterday()

    if start_date is None or start_date > end_date:
        logger.verbose(f"Bigger start date {start_date} than end date {end_date} for station {station_code}")
        return [SeriesJobs(
            HidroTable    = job_config,
            StationID     = station_code,
            FromDate      = start_date,
            ToDate        = end_date,
            Status        = JobConfig.Status.CORRUPTED.value,
        )]

    jobs         = []
    current_year = start_date
    while current_year < end_date:
        try:
            next_year = current_year.replace(year=current_year.year + 1)
        except ValueError:
            next_year = current_year.replace(year=current_year.year + 1, day=28)
        if next_year > end_date:
            next_year = end_date
        jobs.append(SeriesJobs(
            StationID  = station_code,
            FromDate   = current_year,
            ToDate     = next_year,
            Status     = JobConfig.Status.PENDING.value,
            HidroTable = job_config
        ))
        current_year = next_year
    if not jobs:
        jobs.append(SeriesJobs(
            StationID  = station_code,
            FromDate   = start_date,
            ToDate     = end_date,
            Status     = JobConfig.Status.PENDING.value,
            HidroTable = job_config
        ))
    return jobs


def _take_job(jobs, predicate):
    """Remove and return the first job matching ``predicate``."""

    for index, job in enumerate(jobs):
        if predicate(job):
            return jobs.pop(index)
    return None


def _reconcile_jobs(jobs, desired_jobs):
    """Return ``(updates, new_jobs)`` for one station's desired windows."""

    updates, new_jobs = [], []
    for desired in desired_jobs:
        if _take_job(jobs, lambda job:
                     job.FromDate == desired.FromDate and
                     job.ToDate == desired.ToDate):
            continue

        match = _take_job(jobs, lambda job:
                          job.FromDate < desired.ToDate and
                          job.ToDate > desired.FromDate)
        if match is None:
            new_jobs.append(desired)
        else:
            updates.append({
                "ID":       match.ID,
                "FromDate": desired.FromDate,
                "ToDate":   desired.ToDate,
                "Status":   desired.Status,
                "Retries":  0,
            })
    return updates, new_jobs


def update_series_job_windows(job_config: JobConfig, stations_data) -> None:
    """Reconcile existing series jobs with the requested station windows.

    Jobs whose dates already match a desired yearly window are kept
    untouched. When a window changed, an overlapping job is reused and its
    dates are updated; if no overlap exists, a new job is inserted. Jobs
    outside the requested interval are kept but are not queued for this run
    (see :func:`create_job_filters`).
    """

    if not stations_data:
        return

    start_time = time.time()
    chunk_size = _batch_size()
    updated    = 0
    inserted   = 0

    for station_chunk in _chunked(list(stations_data), chunk_size):
        desired = {
            station: process_period(station, from_date, to_date, job_config)
            for station, from_date, to_date in station_chunk
        }
        filters = create_job_filters(
            job_config, [], False, stations=list(desired)
        )
        by_station = {}
        for job in iter_jobs(job_config, filters, chunk_size):
            by_station.setdefault(job.StationID, []).append(job)

        updates, new_jobs = [], []
        for station, desired_jobs in desired.items():
            station_updates, station_new = _reconcile_jobs(
                by_station.get(station, []), desired_jobs
            )
            updates.extend(station_updates)
            new_jobs.extend(station_new)

        for update_chunk in _chunked(updates, chunk_size):
            update_job_mappings(job_config, update_chunk)
        updated += len(updates)

        for job_chunk in _chunked(new_jobs, chunk_size):
            insert_jobs_bulk(job_chunk)
        inserted += len(new_jobs)

    elapsed = time.time() - start_time
    logger.info(
        f"Updated {updated} and inserted {inserted} jobs for {job_config} "
        f"in {elapsed:.2f} seconds"
    )


def update_series_job(job_config: JobConfig) -> None:
    selected    = set(STATIONS)
    station_ids = [
        code for code in
        get_period(job_config, only_code=True, with_null_end_date=True).scalars().all()
        if not selected or code in selected
    ]
    yesterday   = _yesterday()
    updated     = reset_series_job_dates(job_config, station_ids, yesterday, _batch_size())
    logger.trace(f"Updated {updated} stale jobs for {job_config}")


write_queue: Queue[QueueData] = Queue(maxsize=1000)


def _report_future(future) -> None:
    try:
        future.result()
    except Exception as e:
        logger.error(f"[WORKER]: {e}")


def trigger_job(job_config: JobConfig, filters) -> None:
    """ Triggers an Thread Worker for each pending or falied job entrie in DB for a given JobConfig.

    Jobs are streamed in pages and only a bounded number of futures is kept in
    flight. The queue is bounded so slow writes apply backpressure to workers.
    """

    batch_size = _batch_size()
    workers    = max(1, MAX_WORKERS or 1)
    write_queue.maxsize = batch_size

    writer = Thread(target=db_writer, daemon=True)
    writer.start()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = set()
        for job in iter_jobs(job_config, filters, batch_size):
            pending.add(executor.submit(handle_job_request, job, job_config))
            if len(pending) >= 2 * workers:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    _report_future(future)

        for future in as_completed(pending):
            _report_future(future)

    finish_queue = QueueData(
        job_config  = job_config,
        job         = None,
        items       = None,
        worker_time = 0,
        stop_signal = True
    )
    write_queue.put(finish_queue)
    writer.join()
    status_map = {1: "Pending", 2: "Failed", 5: "Completed"}
    counts = {status_map.get(s, f"Unknown({s})"): c for s, c in count_job_by_status(job_config)}
    logger.info(f"Pending: {counts.get('Pending', 0)}, Failed: {counts.get('Failed', 0)}, Completed: {counts.get('Completed', 0)}\n")


token_lock = Lock()
def handle_job_request(job: HidroJob, job_config: JobConfig) -> None:
    """ Request data of an HidroJob.
    Validate data on success return, and convert to ORM model before writing on Queue.
    """

    start = time.time()
    with token_lock:
        token = get_token()
    try:
        success, items = request_job_data(
            job_config, token, job.to_params(FILTER),
            save_json = SAVE_JSON,
            json_dir  = JSON_DIR,
            read_json = READ_JSON,
        )
    except PermissionError:
        logger.warning(f"[WORKER JOB {job.ID}]: Unauthorized, skipping.")
        return

    if success:
        try:
            convert_json_items(job_config, items)
            job.Status = JobConfig.Status.COMPLETED.value
            match job_config:
                case JobConfig.Base():
                    job.LastCheck = datetime.now()
                case JobConfig.Series():
                    if (len(items) > 0):
                        items = validate_series_items(job, job_config, items)
                        if (len(items) > 0):
                            items = validate_series_items_date(job, job_config, items)
        except Exception as e:
            logger.error(f"[WORKER JOB {job.ID}]: {e}, {items}, {type(items)}")
    else:
        job.Status = JobConfig.Status.FAILED.value
        match job_config:
            case JobConfig.Series():
                job.Retries += 1
    if success and items:
        for item in items:
            if isinstance(item, dict):
                item["_JobID"] = job.ID
    elapsed = time.time() - start
    logger.verbose(f"[WORKER]: Job {job.ID} completed in {elapsed:.2f} seconds")
    queue_data = QueueData(
        job_config  = job_config,
        job         = job,
        items       = items,
        worker_time = elapsed,
        stop_signal = False
    )
    write_queue.put(queue_data)


def db_writer() -> None:
    """ Single Writer Thread running during an Job.
    Consumes an Queue writen by each worker and write data in batches.
    """

    batch_buffer = {"jobs": [], "data": []}
    total_data     = 0
    total_jobs     = 0

    worker_elapsed = 0
    total_elapsed  = 0
    insert_elapsed = 0
    batch_elapsed  = 0
    batch_start_time = None
    while True:
        try:
            job_config, job, data, worker_time, stop_signal = write_queue.get()
            worker_elapsed += worker_time
            if job:
                batch_buffer["jobs"].append(job)
            if data:
                batch_buffer["data"].extend(data)
                if batch_start_time is None:
                    batch_start_time = time.time()

            if (len(batch_buffer["data"]) >= BATCH_SIZE or
                len(batch_buffer["jobs"]) >= BATCH_SIZE or stop_signal):
                if batch_start_time is not None:
                    batch_elapsed = time.time() - batch_start_time
                total_data     += len(batch_buffer["data"])
                total_jobs     += len(batch_buffer["jobs"])
                insert_elapsed  = write_data(job_config,
                                             batch_buffer["jobs"],
                                             batch_buffer["data"])
                total_elapsed += batch_elapsed + insert_elapsed

                logger.verbose(f"""[TIMER {job_config}]: """
                               f"""Time to reach batch: {batch_elapsed}, """
                               f"""Time to insert batch: {insert_elapsed}. """)

                logger.info(f"""[WRITER {job_config}]: """
                            f"""Total processed Data: {total_data}, """
                            f"""Total finished Jobs: {total_jobs}. """)
                logger.trace(f"""[TIMER {job_config}]: """
                            f"""Total worker elapsed: {worker_elapsed}, """
                            f"""Total writer elapsed: {total_elapsed}.""")

                batch_buffer["jobs"].clear()
                batch_buffer["data"].clear()
                batch_start_time = None

            if stop_signal:
                logger.info(f"""[WRITER]: Finished jobs for {job_config} """
                            f"""Total processed Data: {total_data}, """
                            f"""Total finished Jobs: {total_jobs}.""")
                logger.info(f"""[WRITER]: Total worker elapsed: {worker_elapsed}, """
                            f"""Total writer elapsed: {total_elapsed}.""")
                break;

        except Exception as e:
            logger.error(f"[WRITER]: db_writer exception: {e}")
            raise

        finally:
            write_queue.task_done()


def _record_provenance(job_config, data_table, items, data_ids=None):
    """Store which job produced each written data row.

    Items written by the API pipeline carry a private ``_JobID`` tag. The
    helper is a no-op for direct calls without that tag, such as the
    round-trip tests.
    """

    if not items:
        return

    if data_ids is None:
        data_ids = get_registro_ids(str(data_table), items)

    records = []
    for item, data_id in zip(items, data_ids):
        job_id = item.get("_JobID")
        if job_id is None or data_id is None:
            continue
        records.append({
            "JobID":     job_id,
            "JobName":   str(job_config),
            "DataTable": str(data_table),
            "DataID":    data_id,
        })
    upsert_job_records(records)


def write_data(job_config: JobConfig, jobs: List[HidroJob], items) -> float:
    """Insert data into DB and update the jobs as well. """

    start_time = time.perf_counter()
    entries = []
    if len(items) > 0:

        match job_config:
            case JobConfig.Series():
                filtered_items = filter_repeated_series_items(job_config, items)

        match job_config:
            case JobConfig.Base():
                entries = handle_batch_update(job_config, items)
                if entries:
                    insert_hidro(entries)
                _record_provenance(job_config, job_config, items)

            case (JobConfig.Series.RAIN          | JobConfig.Series.DISCHARGE_SUMMARY |
                      JobConfig.Series.FLOW_RATE | JobConfig.Series.SEDIMENTS         |
                      JobConfig.Series.STAGE     | JobConfig.Series.GRANULOMETRY      |
                      JobConfig.Series.DISCHARGE_FLOW):
                entries = handle_batch_update(job_config, filtered_items)
                if entries:
                    insert_hidro(entries)
                _record_provenance(job_config, job_config, filtered_items)

            case JobConfig.Series.WATER_QUALITY:
                entries = handle_batch_update(job_config, filtered_items)
                if entries:
                    entries = insert_hidro(entries, False)
                _record_provenance(job_config, job_config, filtered_items)

                lookup = {
                    (entry.EstacaoCodigo, entry.Data): entry.RegistroID
                    for entry in entries
                }
                missing = [
                    item for item in filtered_items
                    if (item['codigoestacao'], item['Data_Hora_Dado']) not in lookup
                ]
                if missing:
                    lookup.update(get_qual_agua_ids(missing))

                for item in filtered_items:
                    item['QualAguaID'] = lookup.get(
                        (item['codigoestacao'], item['Data_Hora_Dado'])
                    )

                status_items = [
                    item for item in filtered_items
                    if item.get('QualAguaID') is not None
                ]
                if status_items:
                    water_status_entries = handle_batch_update(
                        f'{job_config}Status', status_items)
                    if water_status_entries:
                        insert_hidro(water_status_entries)
                    _record_provenance(
                        job_config, f'{job_config}Status', status_items)

            case JobConfig.Series.CROSS_SECTION:
                entries = handle_batch_update(job_config, filtered_items)
                if entries:
                    insert_hidro(entries, False)

                parent_ids = get_registro_ids(str(job_config), filtered_items)
                _record_provenance(
                    job_config, job_config, filtered_items, parent_ids)

                parent_by_key = dict(zip(
                    (item['Registro_ID'] for item in filtered_items),
                    parent_ids,
                ))
                vertical_items = [
                    item for item in items
                    if item.get('Registro_ID') in parent_by_key
                ]
                vertical_entries = [
                    VerticalCrossSection.from_json(
                        item, parent_by_key[item['Registro_ID']]
                    )
                    for item in vertical_items
                ]

                if vertical_entries:
                    inserted = insert_hidro(vertical_entries, False)
                    _record_provenance(
                        job_config,
                        "PerfilTransversalVert",
                        vertical_items,
                        [entry.RegistroID for entry in inserted],
                    )

    if len(jobs) > 0:
        update_jobs(jobs, job_config)
        logger.trace(f"[WRITER {job_config}]: Updated {len(jobs)} jobs")
    elapsed_time = time.perf_counter() - start_time
    if entries:
        logger.trace(f"[WRITER {job_config}]: Inserted {len(entries)} entries in {elapsed_time} seconds")
    return elapsed_time


def validate_series_items(job, job_config: JobConfig, items):
    """Validate if returned data by the API has the expected lenght and keys. """

    optional_keys = []
    match job_config:
        case JobConfig.Series.RAIN:
            dict_len = 76
            expected_keys = [
                "Data_Hora_Dado", "Data_Ultima_Alteracao", "Dia_Maxima", "Maxima", "Maxima_Status", "Nivel_Consistencia", "Numero_Dias_de_Chuva", "Numero_Dias_de_Chuva_Status", "Tipo_Medicao_Chuvas", "Total", "Total_Anual", "Total_Anual_Status", "Total_Status", "codigoestacao"
            ]
            for i in range(1, 32):
                expected_keys.append(f"Chuva_{i:02d}")
                expected_keys.append(f"Chuva_{i:02d}_Status")
        case JobConfig.Series.DISCHARGE_SUMMARY:
            dict_len = 10
            expected_keys = [
                "Area_Molhada (m2)", "Cota (cm)", "Data_Hora_Dado", "Data_Ultima_Alteracao", "Largura (m)", "Nivel_Consistencia", "Profundidade (m)", "Vazao (m3/s)", "Vel_Media (m/s)", "codigoestacao"
            ]
        case JobConfig.Series.DISCHARGE_FLOW:
            dict_len = 18
            expected_keys = [
                "Coef_a", "Coef_h0", "Coef_n", "Coefa_0", "Coefa_1", "Coefa_2", "Coefa_3", "Cota_Maxima", "Cota_Minima", "Data_Ultima_Alteracao", "Nivel_Consistencia", "Numero_Curva", "Periodo_Validade_Fim", "Periodo_Validade_Inicio", "Tabela_Passo_Cota", "Tipo_Curva", "Tipo_Equacao", "codigoestacao"
            ]
        case JobConfig.Series.STAGE:
            dict_len = 78
            expected_keys = [
                "Data_Hora_Dado", "Data_Ultima_Alteracao", "Dia_Maxima", "Dia_Minima", "Maxima", "Maxima_Status", "Media", "Media_Anual", "Media_Anual_Status", "Media_Status", "Mediadiaria", "Minima", "Minima_Status", "Tipo_Medicao_Cotas", "codigoestacao", "nivelconsistencia"
            ]
            for i in range(1, 32):
                expected_keys.append(f"Cota_{i:02d}")
                expected_keys.append(f"Cota_{i:02d}_Status")
        case JobConfig.Series.GRANULOMETRY:
            dict_len = 117
            expected_keys = [
                "codigoestacao", "Nivel_Consistencia", "Data_Dado", "Hora_Final", "Hora_Inicial", "Cota_cm", "Largura_m", "Tipo_Amostra", "Tipo_Coleta", "Tipo_Equip", "Prof_Total_m", "Ordem_Coleta", "Dist_Pto_Inicial_m", "Chuva_Ult_48h", "MatFundo_15_9_mm", "MatFundo_8_0_mm", "MatFundo_4_0_mm", "MatFundo_2_0_mm", "MatFundo_1_0_mm", "MatFundo_0_5_mm", "MatFundo_0_25_mm", "MatFundo_0_125_mm", "MatFundo_0_625_mm", "MatFundo_Argila_%", "MatFundo_Silte_%", "MatFundo_Areia_%", "MatFundo_Pedregulho_%", "MatFundo_0_0_a_0_0156_mm", "MatFundo_0_0157_a_0_02_mm", "MatFundo_0_0201_a_0_0625_mm", "MatFundo_0_0626_a_0_1250_mm", "MatFundo_0_1251_a_0_25_mm", "MatFundo_0_2501_a_0_5_mm", "MatFundo_0_501_a_1_0_mm", "MatFundo_1_0001_a_2_0_mm", "MatFundo_2_0001_a_4_0_mm", "MatFundo_4_0001_a_8_0_mm", "MatFundo_8_0001_a_16_000_mm", "MatFundo_D10_mm", "MatFundo_D16_mm", "MatFundo_D35_mm", "MatFundo_D50_mm", "MatFundo_D65_mm", "MatFundo_D84_mm", "MatFundo_D90_mm", "MatArraste_Vazao_m3_s", "MatArraste_LargRio_m", "MatArraste_LargEquip_m", "MatArraste_PesoMat_g", "MatArraste_VelMedia_m_s", "MatArraste_TempAgua_C", "MatArraste_TempAr_C", "MatArraste_TempoColeta_min", "MatArraste_Arraste_t_dia", "MatArraste_15_9_mm", "MatArraste_8_0_mm", "MatArraste_4_0_mm", "MatArraste_2_0_mm", "MatArraste_1_0_mm", "MatArraste_0_5_mm", "MatArraste_0_25_mm", "MatArraste_0_125_mm", "MatArraste_0_0625_mm", "MatArraste_Argila_%", "MatArraste_Silte_%", "MatArraste_Areia_%", "MatArraste_Pedregulho_%", "MatArraste_0_0_a_0_0156_mm", "MatArraste_0_0157_a_0_02_mm", "MatArraste_0_0201_a_0_0625_mm", "MatArraste_0_0626_a_0_1250_mm", "MatArraste_0_1251_a_0_25_mm", "MatArraste_0_2501_a_0_5_mm", "MatArraste_0_501_a_1_0_mm", "MatArraste_1_0001_a_2_0_mm", "MatArraste_2_0001_a_4_0_mm", "MatArraste_4_0001_a_8_0_mm", "MatArraste_8_0001_a_16_000_mm", "MatArraste_D10_mm", "MatArraste_D16_mm", "MatArraste_D35_mm", "MatArraste_D50_mm", "MatArraste_D65_mm", "MatArraste_D84_mm", "MatArraste_D90_mm", "MatSusp_15_9_mm", "MatSusp_8_0_mm", "MatSusp_4_0_mm", "MatSusp_2_0_mm", "MatSusp_1_0_mm", "MatSusp_0_5_mm", "MatSusp_0_25_mm", "MatSusp_0_125_mm", "MatSusp_0_0625_mm", "MatSusp_Argila_%", "MatSusp_Silte_%", "MatSusp_Areia_%", "MatSusp_Pedregulho_%", "MatSusp_0_0_a_0_0156_mm", "MatSusp_0_0157_a_0_02_mm", "MatSusp_0_0201_a_0_0625_mm", "MatSusp_0_0626_a_0_1250_mm", "MatSusp_0_1251_a_0_25_mm", "MatSusp_0_2501_a_0_5_mm", "MatSusp_0_501_a_1_0_mm", "MatSusp_1_0001_a_2_0_mm", "MatSusp_2_0001_a_4_0_mm", "MatSusp_4_0001_a_8_0_mm", "MatSusp_8_0001_a_16_000_mm", "MatSusp_D10_mm", "MatSusp_D16_mm", "MatSusp_D35_mm", "MatSusp_D50_mm", "MatSusp_D65_mm", "MatSusp_D84_mm", "MatSusp_D90_mm", "Data_Ultima_Alteracao"
            ]
        case JobConfig.Series.CROSS_SECTION:
            dict_len = 18
            expected_keys = [
                "codigoestacao", "Nivel_Consistencia", "Data_Hora_Medicao", "Num_Levantamento", "Tipo_Secao", "Num_Verticais", "Distancia_pipf", "Eixo_X_Dist_Maxima", "Eixo_X_Dist_Minima", "Eixo_Y_Cota_Maxima", "Eixo_Y_Cota_Minima", "Elm_Geom_Passo_Cota", "Observacoes"
            ]
            optional_keys = ["Registro_ID"]
        case JobConfig.Series.WATER_QUALITY:
            dict_len = 303
            expected_keys = [
                "100_2_4_5_t_mgl", "101_2_4_5_tp_mgl", "102_2_4_6_Triclorofenol_mgl", "103_Acido_2_4_Diclorofenoxiacetico_mgl", "104_Aldrin_mgl", "105_Azinfosetil_mgl", "106_Benzeno_mgl", "107_Benzoapireno_mgl", "108_BHC_mgl", "109_Bifenilaspolicloradas_mgl", "10_Escherichiacoli_ufc_100ml", "110_Carbaril_mgl", "111_Clordano_mgl", "112_DDEPP_mgl", "113_DDT_mgl", "114_Demeton_mgl", "115_Diazinon_mgl", "116_Dieldrin_mgl", "117_Dodecaclorononacloro_mgl", "118_Dysystondisulfton_mgl", "119_Endossulfan_mgl", "11_Fitoplancton_Quantitativo_celulas_100ml", "120_Endrin_mgl", "121_Epoxidoheptacloro_mgl", "122_Ethion_mgl", "123_Gution_mgl", "124_Heptacloro_mgl", "125_Lindano_mgl", "126_Malation_mgl", "127_Metilparation_mgl", "128_Metoxicloro_mgl", "129_Paration_mgl", "12_Fosforo_Total_mgl)", "130_Pentaclorofenol_mgl", "131_Phosdrin_mgl", "132_Tetra_Cloreto_Carbono_mgl", "133_Tetra_Cloro_Eteno_mgl", "134_Toxafeno_mgl", "135_Tricloro_Eteno_mgl", "136_Algas_n_upa_ml", "137_Amoniaco_mgl", "138_Bacterias_Heterotroficas_ufc_ml", "139_Cloro_Residual_mgl", "13_Nitratos_mgl_n)", "140_Colifagos_nmp_100ml", "141_Contagem_Bacterias_Placa_ufc_ml", "142_Entero_Bacterias_Patogenicas_n_org_ml", "143_Fungos_ufc_ml", "144_Nitrogenio_Albuminoide_mgl", "145_Protozoarios_n_org_ml", "146_Salmonelas_nmp_ml", "147_Zooplanctontotal_n_org_ml", "14_Nitrogenio_Amoniacal_mgl", "15_Nitrogenio_Total_mgl_n", "16_Ortofosfato_Total_mgl_po4", "17_OD_mgl_02", "18_PH", "19_Soldissolvidos_Totais_mgl", "1_Alcalinidade_Total_mgl_caco3", "20_Solsuspensao_Totais_mgl", "21_Temperatura_Amostra_c", "22_Tempar_c", "23_Transparencia_m", "24_Turbidez_ntu", "25_Acidez_mgl_caco3", "26_Alcalinidade_CO3_mgl", "27_Alcalinidade_HCO3_mgl", "28_Alcalinidade_OH_mgl", "29_Aluminio_Dissolvido_mgl", "2_Carbono_Organico_Total_mgl", "30_Aluminio_mgl_al", "31_Amonia_Nao_Ionizavel_mgl_nh3", "32_Arsenio_mgl", "33_Bario_mgl_ba", "34_Berilio_mgl", "35_Bismuto_Total_mgl", "36_Borodissolvido_mgl", "37_Boro_mgl_b", "38_Cadmio_mgl_cd", "39_Calcio_Total_mgl", "3_Cloretos_mgl_cl", "40_Chumbo_mgl", "41_Cianeto_Livre_mgl", "42_Cianetos_mgl_cn", "43_Cobalto_mgl_co", "44_Cobre_Dissolvido_mgl", "45_Cobre_mgl_cu", "46_Coliformes_Fecais_nmp_100ml", "47_Coliformes_Totais_nmp_100ml", "48_Compostos_Organo_Clorados_mgl", "49_Compostos_Organo_Fosforados_mgl", "50_Condutivida_de_Eletrica_us_cm_a_20c", "51_COR_mg_pt_col", "52_Cromo_Hexavalente_mgl", "53_Cromo_Total_mgl_cr", "54_Cromo_Trivalente_mgl", "55_Densidade_Ciano_Bacterias_cel_ml", "56_Detergentes_mgl_las", "57_Dureza_mgl_caco3", "58_Dureza_Magnesio_mgl_mgco3", "59_Dureza_Total_mgl", "5_Coliformes_Termo_Tolerantes_ufc_100ml", "61_Estreptococos_Fecais_nmp_100ml", "62_Ferro_Dissolvido_mgl", "63_Ferro_Total_mgl", "64_Fluoretos_mgl", "65_Fosfato_Total_mgl", "66_Hidrocarbonetos_mgl", "67_Indicefenois_mgl_c6h5oh", "68_IQA", "69_Litio_mgl", "6_Condutividade_Especifica_25oc_us_cm_a_25c", "70_Magnesio_Total_mgl", "71_Manganes_mgl", "72_Mercurio_mgl", "73_Niquel_mgl", "74_Nitritos_mgl", "75_Nitrogenio_Organico_mgl", "76_Nitrogenio_Total_kjeldahl_mgl", "77_Oleos_graxas_mgl", "78_OD_perc_saturacao", "79_Potassio_Total_mgl", "7_DBO_mgl_02)", "80_Prata_mgl", "81_Parametro_Profundidade_m", "82_Selenio_mgl", "83_Silicadissolvida_mgl", "84_Sodiototal_mgl", "85_Soldissolvidos_Fixos_mgl_a_180c)", "86_Soldissolvidos_Volateis_mgl", "87_Sol_Suspensao_Fixos_mgl", "88_Sol_Suspensao_Volateis_mgl", "89_Solfixos_mgl", "8_Descarga_Liquida_m3s", "90_Sol_sedimentaveis_mgl", "91_Sol_totais_mgl", "92_Sol_Volateis_mgl", "93_Sulfatos_mgl", "94_Sulfetos_mgl", "95_Uranio_Total_mgl", "96_Vanadio_mgl", "97_Zinco_mgl", "98_1_1_Dicloroeteno_mgl", "99_1_2_Dicloroetano_mgl", "9_DQO_mgl_02)", "Choveu", "Data_Hora_Dado", "Data_Ultima_Alteracao", "Nilvel_ConsistÃªncia", "Num_Medicao", "Posicao_Horizontal_Coleta", "Posicao_Vertical_Coleta", "Profundidade_m", "codigoestacao"
            ]
            for i in range(1, 148):
                expected_keys.append(f"{i}_Status")
        case JobConfig.Series.SEDIMENTS:
            dict_len = 18
            expected_keys = [
                "Area_Molhada", "Concentracao_PPM", "Concentracao_da_Amostra_Extra", "Condutividade_Eletrica", "Cota_cm", "Cota_de_Mediacao", "Data_Hora_Dado", "Data_Hora_Medicao_Liquida", "Data_Ultima_Alteracao", "Largura", "Nivel_Consistencia", "Numero_Medicao", "Numero_Medicao_Liquida", "Observacoes", "Temperatura_da_Agua", "Vazao_m3_s", "Vel_Media", "codigoestacao"
            ]
        case JobConfig.Series.FLOW_RATE:
            dict_len = 78
            expected_keys = [
                "codigoestacao", "Nivel_Consistencia", "Data_Hora_Dado", "Mediadiaria", "Metodo_Obtencao_Vazoes", "Maxima", "Minima", "Media", "Dia_Maxima", "Dia_Minima", "Maxima_Status", "Minima_Status", "Media_Status", "Media_Anual", "Media_Anual_Status", "Data_Ultima_Alteracao"
            ]
            for i in range(1, 32):
                expected_keys.append(f"Vazao_{i:02d}")
                expected_keys.append(f"Vazao_{i:02d}_Status")

    min_len = dict_len - len(optional_keys)
    valid = []
    for index, item in enumerate(items):
        if len(item) < min_len or len(item) > dict_len:
            logger.verbose(f"[VALIDATE LEN Job {job.ID}] Item index {index} has length {len(item)}, expected {min_len} to {dict_len}")
            continue
        if not all(key in item for key in expected_keys):
            missing = ', '.join([key for key in expected_keys if key not in item])
            logger.verbose(f"[VALIDATE LEN Job {job.ID}] Item index {index} has missing key(s) {missing}")
            continue
        logger.verbose(f"[VALIDATE LEN Job {job.ID}] Appending item index {index}.")
        valid.append(item)

    if len(valid) == 0:
        job.Status   = JobConfig.Status.FAILED.value
        job.Retries += 1
    return valid


def validate_series_items_date(job, job_config: JobConfig, items):
    """Validate if returned data by the API has the expected date interval. """

    match job_config:
        case JobConfig.Series.DISCHARGE_FLOW:
            return items

    valid = []
    for index, item in enumerate(items):
        try:
            match job_config:
                case (JobConfig.Series.RAIN          | JobConfig.Series.DISCHARGE_SUMMARY |
                      JobConfig.Series.SEDIMENTS     | JobConfig.Series.FLOW_RATE         |
                      JobConfig.Series.WATER_QUALITY | JobConfig.Series.STAGE):
                    key = 'Data_Hora_Dado'
                case JobConfig.Series.GRANULOMETRY:
                    key = 'Data_Dado'
                case JobConfig.Series.CROSS_SECTION:
                    key = 'Data_Hora_Medicao'
            date = item.get(key)
            if date is None:
                logger.verbose(f"Item index {index} has missing key {key}.")
                continue
            date = date.replace(hour=0, minute=0, second=0)
            if date < job.FromDate:
                logger.verbose(f"Item index {index} has invalid date {date}, lesser than job FromDate {job.FromDate}")
                continue
            if date > job.ToDate:
                logger.verbose(f"Item index {index} has invalid date {date}, bigger than job FromDate {job.ToDate}")       
                continue

            valid.append(item)

        except Exception as e:
            logger.error(f"[VALIDATE DATE JOB {job.ID}] Error at index {index}: {e}, item type: {type(item)}")
            pass

    return valid


def filter_repeated_series_items(job_config: JobConfig, items):
    """Filter repeated items before writing on database. """

    seen = set()
    filtered = []
    for index, item in enumerate(items):
        try:
            match job_config:
                case (JobConfig.Series.RAIN      | JobConfig.Series.WATER_QUALITY |
                      JobConfig.Series.STAGE     | JobConfig.Series.FLOW_RATE     |
                      JobConfig.Series.SEDIMENTS):
                    key = (item['codigoestacao'], item['Data_Hora_Dado'])
                case JobConfig.Series.DISCHARGE_SUMMARY:
                    key = tuple(sorted(
                        (k, str(v)) for k, v in item.items()
                        if not k.startswith("_")
                    ))
                case JobConfig.Series.GRANULOMETRY:
                    key = (item['codigoestacao'], item['Data_Dado'],
                           item['Hora_Inicial'], item['Hora_Final'])
                case JobConfig.Series.DISCHARGE_FLOW:
                    item['Numero_Curva'] = str(item['Numero_Curva'])
                    key = (item['codigoestacao'], item['Numero_Curva'],
                           item['Periodo_Validade_Inicio'], item['Periodo_Validade_Fim'])
                case JobConfig.Series.CROSS_SECTION:
                    key = item.get('Registro_ID')
                    if key is None:
                        continue
            if key not in seen:
                seen.add(key)
                filtered.append(item)
            else:
                logger.verbose(f"[VALIDATE JOB]: Duplicated item: {key}")

        except Exception as e:
            logger.error(f"[FILTER] Error at index {index}: {e}")
            pass

    return filtered


def convert_json_items(job_config, items):
    """Convert returned data by API to python types. """

    if isinstance(items, dict):
        items = [items]

    formats = ["%Y-%m-%d %H:%M:%S.%f",
               "%Y-%m-%d %H:%M:%S",
               "%Y-%m-%d", "%H:%M:%S"]
    for item in items:
        for key, value in item.items():
            if isinstance(value, str):
                try:
                    item[key] = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    for fmt in formats:
                        try:
                            item[key] = datetime.strptime(value, fmt)
                            break
                        except ValueError:
                            continue
    return items


def run():
    for job in JobConfig.Base:
        logger.info(f"====================================")
        check_base_job(job)
        logger.info(f"====================================\n")

    if SKIP_SERIES_JOBS:
        logger.info(f"====================================")
        logger.info(f"Skiping series jobs.\n")
        logger.info(f"====================================")
        return

    for job in JobConfig.Series:
        logger.info(f"====================================")
        if job in SKIP_FOR:
            logger.info(f"Skiping job for {job}.")
            logger.info(f"====================================\n")
            continue
        if len(RUN_FOR) > 0:
            if job not in RUN_FOR:
                logger.info(f"Skiping job for {job}.")
                logger.info(f"====================================\n")
                continue
        check_series_job(job)
        logger.info(f"====================================\n")

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

import logging, os, sys, time
logger = logging.getLogger(__name__)

from concurrent.futures import (
    ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED,
)
from threading          import Thread, Lock
from queue              import Queue

from datetime    import datetime, timedelta, date
from typing      import List, NamedTuple, Optional

from hidrocli.database import (
    HidroJob, SeriesJobs, Token, JobStatus, BaseTables, SeriesTables,
)

from hidrocli.database.client import (
    add_token, count_client, count_job, count_job_by_status,
    create_job_filters, get_credentials, get_job_model, get_station_ids,
    get_token_model, insert_jobs, insert_jobs_bulk, iter_jobs,
    make_series_job, reset_series_job_dates, update_job_mappings, update_jobs,
    update_token, upsert_job_records,
)
from hidrocli.database.hidro import (
    get_period, get_qual_agua_ids, get_registro_ids, get_states,
    handle_batch_update, insert_hidro, make_vertical_cross_section,
    normalize_items, coerce_value,
)

from requests.exceptions import HTTPError, RequestException

from tqdm import tqdm

from hidrocli.config import Config

from hidrocli.webservices import request_job_data, request_token

from hidrocli.jobs import DedupMode, expected_keys, get_date_key, get_dedup


CONFIG: Config = Config()
"""Frozen run configuration, set once by :func:`run` before jobs execute."""


JOB_CHUNK_SIZE = 5000
"""Minimum number of jobs to accumulate before one bulk insert."""


PROGRESS_INTERVAL = 10.0
"""Seconds between progress lines emitted by the writer thread."""


class JobConfig:
    """ Job name groups and status. """

    Base   = BaseTables
    Series = SeriesTables
    Status = JobStatus


class QueueData(NamedTuple):
    """Interface data expected by the writer thread."""

    job_config:  JobConfig
    job:         HidroJob
    items:       dict
    worker_time: float
    stop_signal: bool


def _batch_size() -> int:
    """Return the configured write/job chunk size, with a safe default."""

    return max(1, CONFIG.BATCH_SIZE)


def _chunked(items, size: int):
    """Yield ``items`` in lists of at most ``size`` entries."""

    size = max(1, size)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _interactive() -> bool:
    """True when stderr is a real terminal that supports in-place redraws.

    ``TERM=dumb`` (or an unset ``TERM``) marks a terminal that cannot redraw
    a line in place, so it falls back to the line-based heartbeat instead.
    """

    if not sys.stderr.isatty():
        return False
    return os.environ.get("TERM", "") not in ("", "dumb")


def _make_progress_bar(total: int, desc: str, unit: str):
    """Return a tqdm bar, disabled when stderr is not a terminal.

    ``unit`` is prefixed with a space so the rate renders as ``12.3 job/s``
    rather than tqdm's cramped ``12.3job/s``. The remaining-time estimate is
    dropped so the bar reads ``[elapsed, rate]`` instead of ``[elapsed<eta]``.
    """

    return tqdm(
        total=total,
        desc=desc,
        unit=f" {unit}",
        bar_format=(
            "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} "
            "[{elapsed}, {rate_fmt}{postfix}]"
        ),
        disable=not _interactive(),
        file=sys.stderr,
    )


def _announce(message: str) -> None:
    """Log an INFO line, suppressed while a live progress bar is active."""

    if not _interactive():
        logger.info(message)


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

    _announce("No valid token present, requesting.")
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

    _announce("Token acquired and cached.")
    return token


def check_base_job(job_config: JobConfig.Base) -> None:
    """Checks each HidroJob and request/update them.

    :param job: Current Job to check, insert and update.
    :returns: Nothing.
    """

    filters = create_job_filters(job_config, None, last_check=False)
    if not count_job(job_config, filters):
        _announce(f"Creating jobs for {job_config}.")
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
            _announce(f"Initiating jobs for {job_config}")
            trigger_job(job_config, filters, count)
            check_base_job(job_config)
        else:
            _announce(f"No pending jobs for {job_config}.")


def check_series_job(job_config: JobConfig) -> None:
    """Checks an JobConfig.
    Create missing station jobs and start pending jobs requisition.
    """

    selected    = set(CONFIG.STATIONS)
    period_data = []
    for data in get_period(job_config).all():
        if selected and data[0] not in selected:
            continue
        start = CONFIG.INITIAL_DATE if CONFIG.INITIAL_DATE is not None else data[1]
        end   = CONFIG.FINAL_DATE   if CONFIG.FINAL_DATE   is not None else data[2]
        period_data.append((data[0], _as_datetime(start), _as_datetime(end)))

    if selected:
        missing_stations = selected - {data[0] for data in period_data}
        if missing_stations:
            logger.warning(
                f"No period data for stations {sorted(missing_stations)} "
                f"in {job_config}."
            )

    existing = get_station_ids(job_config, CONFIG.STATIONS)
    missing  = [data for data in period_data if data[0] not in existing]
    if missing:
        _announce(f"Creating jobs from {len(missing)} stations for {job_config}")
        create_series_jobs(missing, job_config)

    if CONFIG.INITIAL_DATE is not None or CONFIG.FINAL_DATE is not None:
        update_series_job_windows(
            job_config,
            [data for data in period_data if data[0] in existing],
        )

    if CONFIG.FINAL_DATE is None:
        update_series_job(job_config)
    trigger_series_jobs(job_config)


def trigger_series_jobs(job_config: JobConfig) -> None:
    """Trigger pending and failed jobs, retrying within the same run."""

    status = [JobConfig.Status.FAILED.value, JobConfig.Status.PENDING.value]
    filters = create_job_filters(job_config, status, last_check=False,
                                 stations=CONFIG.STATIONS, max_retries=True,
                                 initial_date=CONFIG.INITIAL_DATE,
                                 final_date=CONFIG.FINAL_DATE)
    count = count_job(job_config, filters)
    if count:
        _announce(f"Initiating {count} jobs for {job_config}")
        trigger_job(job_config, filters, count)
        trigger_series_jobs(job_config)
    else:
        _announce(f"No pending jobs for {job_config}.")


def create_series_jobs(stations_data: List, job_config: JobConfig) -> None:
    """ Creates Series Jobs for each station received for a given JobConfig.
    Preprocess all years from "Start Date" to "End Date" that will become a job request.
    Jobs are written in bounded chunks to keep memory flat.
    """
    start      = time.time()
    chunk_size = max(_batch_size(), JOB_CHUNK_SIZE)
    workers    = max(1, CONFIG.MAX_WORKERS)
    batch      = []
    created    = 0

    bar = _make_progress_bar(
        len(stations_data), f"Create {job_config}", "station"
    )

    def collect(future):
        nonlocal created
        try:
            processed_jobs = future.result()
        except Exception as e:
            logger.error(f"Error processing period: {e}")
            bar.update(1)
            return
        batch.extend(processed_jobs)
        if len(batch) >= chunk_size:
            insert_jobs_bulk(batch)
            created += len(batch)
            batch.clear()
        bar.set_postfix(jobs=created + len(batch), refresh=False)
        bar.update(1)

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

    bar.close()

    elapsed = time.time() - start
    _announce(f"Created {created} jobs for {job_config} in {elapsed:.2f} seconds")


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
        return [make_series_job(
            station_code, start_date, end_date,
            JobConfig.Status.CORRUPTED.value, job_config,
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
        jobs.append(make_series_job(
            station_code, current_year, next_year,
            JobConfig.Status.PENDING.value, job_config,
        ))
        current_year = next_year
    if not jobs:
        jobs.append(make_series_job(
            station_code, start_date, end_date,
            JobConfig.Status.PENDING.value, job_config,
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
    _announce(
        f"Updated {updated} and inserted {inserted} jobs for {job_config} "
        f"in {elapsed:.2f} seconds"
    )


def update_series_job(job_config: JobConfig) -> None:
    selected    = set(CONFIG.STATIONS)
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


def trigger_job(job_config: JobConfig, filters, total: int) -> None:
    """ Triggers an Thread Worker for each pending or falied job entrie in DB for a given JobConfig.

    Jobs are streamed in pages and only a bounded number of futures is kept in
    flight. The queue is bounded so slow writes apply backpressure to workers.

    A tqdm bar reports jobs completed against ``total`` on a terminal. When
    output is redirected the bar is disabled and the writer's throttled
    heartbeat lines report progress instead.
    """

    batch_size = _batch_size()
    workers    = max(1, CONFIG.MAX_WORKERS)
    write_queue.maxsize = batch_size

    bar = _make_progress_bar(total, f"Request {job_config}", "job")
    interactive = not bar.disable

    writer = Thread(target=db_writer, args=(interactive,), daemon=True)
    writer.start()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = set()
        for job in iter_jobs(job_config, filters, batch_size):
            pending.add(executor.submit(handle_job_request, job, job_config))
            if len(pending) >= 2 * workers:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    _report_future(future)
                bar.update(len(done))

        for future in as_completed(pending):
            _report_future(future)
            bar.update(1)

    finish_queue = QueueData(
        job_config  = job_config,
        job         = None,
        items       = None,
        worker_time = 0,
        stop_signal = True
    )
    write_queue.put(finish_queue)
    writer.join()

    status_map = {1: "Pending", 2: "Failed", 3: "Invalid", 5: "Completed"}
    counts = {status_map.get(s, f"Unknown({s})"): c for s, c in count_job_by_status(job_config)}
    summary = ", ".join(
        f"{key}: {counts.get(key, 0)}"
        for key in ("Pending", "Failed", "Invalid", "Completed")
    )

    bar.set_postfix_str(summary, refresh=False)
    bar.close()
    _announce(summary)


token_lock = Lock()

SERVER_ERROR_BACKOFF = 60.0
"""Seconds the whole worker pool pauses after a 5xx server response."""

_backoff_lock = Lock()
_backoff_until = 0.0
"""Monotonic timestamp until which every worker pauses between requests."""


def _backoff_pool() -> None:
    """Make every worker pause until the backoff window expires."""

    global _backoff_until
    with _backoff_lock:
        _backoff_until = max(_backoff_until, time.monotonic() + SERVER_ERROR_BACKOFF)


def _wait_backoff() -> None:
    """Sleep if a previous 5xx response put the pool in a cooldown window."""

    with _backoff_lock:
        remaining = _backoff_until - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def _mark_failed(job: HidroJob, job_config: JobConfig) -> None:
    """Mark a job FAILED and, for series jobs, bump its retry count."""

    job.Status = JobConfig.Status.FAILED.value
    match job_config:
        case JobConfig.Series():
            job.Retries += 1


def _is_sql_grammar(response) -> bool:
    """Return True when the response body is the 417 SQLGrammarException."""

    if response is None:
        return False
    try:
        body = response.json()
    except Exception:
        return False
    return (isinstance(body, dict)
            and body.get("code") == 417
            and body.get("status") == "EXPECTATION_FAILED"
            and "SQLGrammarException" in str(body.get("message", "")))


def _handle_http_error(job: HidroJob, job_config: JobConfig, e) -> bool:
    """Apply an HTTPError to the job. Return True when the job is skipped."""

    code = e.response.status_code if e.response is not None else None
    if code == 401:
        logger.warning(f"[WORKER JOB {job.ID}]: Unauthorized, skipping.")
        return True
    if code is not None and 500 <= code < 600:
        _backoff_pool()
        logger.verbose(f"[WORKER JOB {job.ID}]: Server error {code}, skipping.")
        return True
    if code == 417 and _is_sql_grammar(e.response):
        logger.verbose(f"[WORKER JOB {job.ID}]: {job_config} invalid: {e}")
        job.Status = JobConfig.Status.INVALID.value
    else:
        logger.error(f"[WORKER JOB {job.ID}]: unhandled HTTP error: {e}")
        _mark_failed(job, job_config)
    return False


def _process_success(job: HidroJob, job_config: JobConfig, items):
    """Normalize and validate fetched items, marking the job COMPLETED."""

    try:
        items = normalize_items(str(job_config), items)
        job.Status = JobConfig.Status.COMPLETED.value
        match job_config:
            case JobConfig.Base():
                job.LastCheck = datetime.now()
            case JobConfig.Series():
                if items:
                    items = validate_series_items(job, job_config, items)
                    if items:
                        items = validate_series_items_date(job, job_config, items)
    except Exception as e:
        logger.error(f"[WORKER JOB {job.ID}]: {e}, {items}, {type(items)}")
    return items


def handle_job_request(job: HidroJob, job_config: JobConfig) -> None:
    """ Request data of an HidroJob.
    Validate data on success return, and convert to ORM model before writing on Queue.
    """

    _wait_backoff()
    start = time.time()
    success, items = False, []
    try:
        with token_lock:
            token = get_token()
        success, items = request_job_data(
            job_config, token, job.to_params(CONFIG.FILTER),
            save_json = CONFIG.SAVE_JSON,
            json_dir  = CONFIG.JSON_DIR,
            read_json = CONFIG.READ_JSON,
        )
    except HTTPError as e:
        if _handle_http_error(job, job_config, e):
            return
    except RequestException as e:
        logger.trace(f"[WORKER JOB {job.ID}]: Request error, skipping. {e}")
        return
    except Exception as e:
        logger.error(f"[WORKER JOB {job.ID}]: unhandled error: {e}")
        _mark_failed(job, job_config)
    else:
        if success:
            items = _process_success(job, job_config, items)
        else:
            logger.trace(f"[WORKER JOB {job.ID}]: {job_config} request failed, marking job as FAILED")
            _mark_failed(job, job_config)

    if success and items:
        for item in items:
            if isinstance(item, dict):
                item["_JobID"] = job.ID
    write_queue.put(QueueData(
        job_config  = job_config,
        job         = job,
        items       = items,
        worker_time = time.time() - start,
        stop_signal = False
    ))


def db_writer(interactive=False) -> None:
    """ Single Writer Thread running during an Job.
    Consumes an Queue writen by each worker and write data in batches.

    When ``interactive`` is true (a live tqdm bar is active), the writer skips
    the throttled heartbeat and final summary, since the bar reports progress.
    Otherwise (output is redirected) it emits those lines.
    """

    batch_buffer = {"jobs": [], "data": []}
    total_data     = 0
    total_jobs     = 0

    worker_elapsed = 0
    total_elapsed  = 0
    insert_elapsed = 0
    batch_elapsed  = 0
    batch_start_time = None
    last_report = time.monotonic()
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

            now = time.monotonic()
            if (not interactive and not stop_signal and
                    now - last_report >= PROGRESS_INTERVAL):
                processed_rows = total_data + len(batch_buffer["data"])
                processed_jobs = total_jobs + len(batch_buffer["jobs"])
                logger.info(f"[WRITER {job_config}]: "
                            f"{processed_rows} rows, {processed_jobs} jobs")
                last_report = now

            if (len(batch_buffer["data"]) >= CONFIG.BATCH_SIZE or
                len(batch_buffer["jobs"]) >= CONFIG.BATCH_SIZE or stop_signal):
                if batch_start_time is not None:
                    batch_elapsed = time.time() - batch_start_time
                total_data     += len(batch_buffer["data"])
                total_jobs     += len(batch_buffer["jobs"])
                insert_elapsed  = write_data(job_config,
                                             batch_buffer["jobs"],
                                             batch_buffer["data"])
                total_elapsed += batch_elapsed + insert_elapsed

                logger.trace(f"[TIMER {job_config}]: "
                             f"batch {batch_elapsed:.2f}s, insert {insert_elapsed:.2f}s")

                batch_buffer["jobs"].clear()
                batch_buffer["data"].clear()
                batch_start_time = None

            if stop_signal:
                if not interactive:
                    logger.info(f"[WRITER {job_config}]: {total_data} rows, "
                                f"{total_jobs} jobs in {worker_elapsed:.2f}s worker / "
                                f"{total_elapsed:.2f}s writer")
                break

        except Exception as e:
            logger.error(f"[WRITER]: db_writer exception: {e}")
            raise

        finally:
            write_queue.task_done()


def _record_provenance(job_config, data_table, items, data_ids=None):
    """Store which job produced each written data row.

    Items written by the API pipeline carry a private ``_JobID`` tag. The
    helper is a no-op for direct calls without that tag, such as the
    round-trip tests, and for runs where ``CONFIG.TRACE_RECORDS`` is disabled.
    """

    if not CONFIG.TRACE_RECORDS or not items:
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


def _upsert(data_table, items):
    """Insert or update ``items`` and return the newly created rows."""

    entries = handle_batch_update(data_table, items)
    if entries:
        insert_hidro(entries, expire=False)
    return entries


def _water_quality_status_items(items, entries):
    """Attach each item's ``QualAguaID`` and keep rows with a resolved parent."""

    lookup = {(entry.EstacaoCodigo, entry.Data): entry.RegistroID
              for entry in entries}
    missing = [
        item for item in items
        if (item['EstacaoCodigo'], item['Data']) not in lookup
    ]
    if missing:
        lookup.update(get_qual_agua_ids(missing))

    for item in items:
        item['QualAguaID'] = lookup.get(
            (item['EstacaoCodigo'], item['Data'])
        )

    return [item for item in items if item['QualAguaID'] is not None]


def _vertical_cross_section_entries(items, parent_items, parent_ids):
    """Build one vertical row per raw item, linked to its parent section."""

    parent_by_key = dict(zip(
        (item['ANA_RegistroID'] for item in parent_items), parent_ids))
    vertical_items = [
        item for item in items
        if item.get('ANA_RegistroID') in parent_by_key
    ]
    return vertical_items, [
        make_vertical_cross_section(
            item, parent_by_key[item['ANA_RegistroID']]
        )
        for item in vertical_items
    ]


def write_data(job_config: JobConfig, jobs: List[HidroJob], items) -> float:
    """Insert data into DB and update the jobs as well. """

    start_time = time.perf_counter()
    entries = []

    if items:
        filtered_items = items
        if not isinstance(job_config, JobConfig.Base):
            filtered_items = filter_repeated_series_items(job_config, items)

        match job_config:
            case (JobConfig.Series.RAIN           | JobConfig.Series.DISCHARGE_SUMMARY |
                  JobConfig.Series.FLOW_RATE      | JobConfig.Series.SEDIMENTS         |
                  JobConfig.Series.STAGE          | JobConfig.Series.GRANULOMETRY      |
                  JobConfig.Series.DISCHARGE_FLOW | JobConfig.Base()):
                entries = _upsert(job_config, filtered_items)
                _record_provenance(job_config, job_config, filtered_items)

            case JobConfig.Series.WATER_QUALITY:
                entries = _upsert(job_config, filtered_items)
                _record_provenance(job_config, job_config, filtered_items)

                status_items = _water_quality_status_items(filtered_items, entries)
                if status_items:
                    _upsert(f'{job_config}Status', status_items)
                    _record_provenance(job_config, f'{job_config}Status', status_items)

            case JobConfig.Series.CROSS_SECTION:
                parent_items = filtered_items
                entries = _upsert(job_config, parent_items)
                parent_ids = get_registro_ids(str(job_config), parent_items)
                _record_provenance(job_config, job_config, parent_items, parent_ids)

                # Levels live in the raw items; parent rows are deduplicated.
                vertical_items, vertical_entries = _vertical_cross_section_entries(
                    items, parent_items, parent_ids)
                if vertical_entries:
                    inserted = insert_hidro(vertical_entries, expire=False)
                    _record_provenance(
                        job_config,
                        "PerfilTransversalVert",
                        vertical_items,
                        [entry.RegistroID for entry in inserted],
                    )

    if jobs:
        update_jobs(jobs, job_config)
        logger.trace(f"[WRITER {job_config}]: Updated {len(jobs)} jobs")
    elapsed_time = time.perf_counter() - start_time
    if entries:
        logger.trace(f"[WRITER {job_config}]: Inserted {len(entries)} entries in {elapsed_time} seconds")
    return elapsed_time


def validate_series_items(job, job_config: JobConfig, items):
    """Validate if returned data by the API has the expected keys."""

    optional_keys, required = expected_keys(str(job_config))
    valid = []
    for index, item in enumerate(items):
        if not all(key in item for key in required):
            missing = ', '.join([key for key in required if key not in item])
            logger.verbose(f"[VALIDATE Job {job.ID}] Item index {index} has missing key(s) {missing}")
            continue
        logger.verbose(f"[VALIDATE Job {job.ID}] Appending item index {index}.")
        valid.append(item)

    if len(valid) == 0:
        _mark_failed(job, job_config)
    return valid


def validate_series_items_date(job, job_config: JobConfig, items):
    """Validate if returned data by the API has the expected date interval."""

    date_key = get_date_key(str(job_config))
    if date_key is None:
        return items

    valid = []
    for index, item in enumerate(items):
        try:
            date = item.get(date_key)
            if date is None:
                logger.verbose(f"Item index {index} has missing key {date_key}.")
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


def _dedup_key(dedup, item):
    """Compute the dedup key for ``item`` following ``dedup`` (a ``Dedup``)."""

    if dedup.mode == DedupMode.WHOLE:
        return tuple(sorted(
            (k, str(v)) for k, v in item.items()
            if not k.startswith("_")
        ))
    if dedup.mode == DedupMode.SINGLE:
        return item.get(dedup.keys[0])

    for key in dedup.stringify:
        item[key] = str(item[key])
    return tuple(item[key] for key in dedup.keys)


def filter_repeated_series_items(job_config: JobConfig, items):
    """Filter repeated items before writing on database."""

    dedup = get_dedup(str(job_config))
    seen = set()
    filtered = []
    for index, item in enumerate(items):
        try:
            key = _dedup_key(dedup, item)
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
    """Coerce string values to Python types (keeps the raw ANA keys)."""

    if isinstance(items, dict):
        items = [items]

    for item in items:
        for key, value in item.items():
            item[key] = coerce_value(value)
    return items


def run(config: Config):
    """Run every base and series job using ``config``."""

    global CONFIG
    CONFIG = config
    rule = "-" * 40 + "\n"  # trailing newline leaves a blank line for navigation

    for job in JobConfig.Base:
        _announce(rule)
        check_base_job(job)

    if CONFIG.SKIP_SERIES_JOBS:
        _announce(rule)
        _announce("Skiping series jobs.")
        return

    for job in JobConfig.Series:
        _announce(rule)
        if job in CONFIG.SKIP_FOR:
            _announce(f"Skiping job for {job}.")
            continue
        if len(CONFIG.RUN_FOR) > 0:
            if job not in CONFIG.RUN_FOR:
                _announce(f"Skiping job for {job}.")
                continue
        check_series_job(job)

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

import logging, os, random, sys, time
logger = logging.getLogger(__name__)

from concurrent.futures import (
    ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED,
)
from threading          import Thread, Lock, Condition
from queue              import Queue

from datetime    import datetime, timedelta, date
from typing      import List, NamedTuple, Optional

from hidrocli.database import (
    HidroJob, SeriesJobs, TelemetryJobs, Token, JobStatus, BaseTables,
    SeriesTables, TelemetryTables,
)

from hidrocli.database.client import (
    add_token, count_client, count_job, count_job_by_status,
    create_job_filters, get_credentials, get_job_model, get_station_ids,
    get_telemetry_job_bounds, get_telemetry_job_keys, get_token_model,
    insert_jobs, insert_jobs_bulk, iter_jobs, make_series_job,
    reset_series_job_dates, update_job_mappings, update_jobs, update_token,
    upsert_job_records,
)
from hidrocli.database.hidro import (
    get_period, get_qual_agua_ids, get_registro_ids, get_states,
    get_telemetry_stations, insert_hidro, make_vertical_cross_section,
    normalize_items, upsert_items,
)

from requests.exceptions import HTTPError, RequestException, Timeout

from tqdm import tqdm

from hidrocli.config import Config

from hidrocli.webservices import request_job_data, request_token

from hidrocli.jobs import DedupMode, expected_keys, get_date_key, get_dedup


CONFIG: Config = Config()
"""Frozen run configuration, set once by :func:`run` before jobs execute."""


BULK_SIZE = 5000
"""Minimum jobs or rows accumulated before one bulk write.

Independent of ``--batch-size`` (which bounds the scheduling page and queue):
a larger batch means fewer SQLite commits without hydrating more jobs.
"""


SERIES_RETRY_DEPTH = 3
"""Additional same-run retry passes after the first series scheduling pass."""


PROGRESS_INTERVAL = 10.0
"""Seconds between progress lines emitted by the writer thread."""


ADAPTIVE_INITIAL = 8
"""Initial in-flight request limit for adaptive concurrency."""


ADAPTIVE_INCREASE_AFTER = 5
"""Successful requests before the additive limit grows by one, after a throttle."""


ADAPTIVE_PAUSE = 5.0
"""Base pause (seconds) after the API asks us to slow down."""


class _AdaptiveLimiter:
    """Limit in-flight requests and adapt to server back-pressure.

    The limit doubles each full window of successes during the initial ramp
    (TCP-style slow start), then grows additively after a throttle. A throttle
    response (429/5xx) halves the limit and applies a short jittered pause so
    retries do not synchronise. This avoids bursting the API without a fixed
    cap while still reaching the server's capacity quickly.
    """

    def __init__(self, initial: int, maximum: int):
        self.maximum   = max(1, maximum)
        self.limit     = max(1, min(initial, self.maximum))
        self.active    = 0
        self.successes = 0
        self.errors    = 0
        self.slow_start  = True
        self.pause_until = 0.0
        self.condition = Condition()

    def acquire(self) -> None:
        """Block until an in-flight slot is available."""

        with self.condition:
            while True:
                now = time.monotonic()
                if self.active < self.limit and now >= self.pause_until:
                    self.active += 1
                    return
                timeout = self.pause_until - now if now < self.pause_until else None
                self.condition.wait(timeout=timeout)

    def release(self) -> None:
        """Return an in-flight slot."""

        with self.condition:
            self.active -= 1
            self.condition.notify()

    def success(self) -> None:
        """Record a successful request and grow the limit."""

        with self.condition:
            if self.limit >= self.maximum:
                return

            self.successes += 1
            if self.slow_start:
                # Double once a full window of the current limit succeeds.
                if self.successes >= self.limit:
                    self.limit = min(self.maximum, self.limit * 2)
                    self.successes = 0
                    self.condition.notify_all()
            elif self.successes >= ADAPTIVE_INCREASE_AFTER:
                self.limit += 1
                self.successes = 0
                self.condition.notify()

    def throttled(self) -> None:
        """Halve the limit and pause briefly after a throttle response."""

        with self.condition:
            self.errors += 1
            self.slow_start = False
            self.limit = max(1, self.limit // 2)
            self.successes = 0
            pause = ADAPTIVE_PAUSE * random.uniform(0.5, 1.5)
            now = time.monotonic()
            self.pause_until = max(self.pause_until, now + pause)
            self.condition.notify_all()


class JobConfig:
    """ Job name groups and status. """

    Base      = BaseTables
    Series    = SeriesTables
    Telemetry = TelemetryTables
    Status    = JobStatus


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


def _thread_limit() -> int:
    """Return the OS soft limit on concurrent threads, minus a small reserve.

    Clamps ``--max-workers`` for request threads. The ANA API can still
    saturate or return HTTP 503 well before this limit is reached.
    """

    try:
        import resource
        soft, _ = resource.getrlimit(resource.RLIMIT_NPROC)
    except (AttributeError, ImportError, ValueError, OSError):
        return os.cpu_count() or 1

    if soft < 0:  # RLIM_INFINITY
        return os.cpu_count() or 1
    return max(1, soft - 8)


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


def _clock(seconds: float) -> str:
    """Format seconds as ``MM:SS`` (or ``H:MM:SS`` past an hour)."""

    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _bar_stats(bar, label: str, unit: str, created=None, updated=None,
               workers=None, errors=None, limiter=None, throttle=None) -> str:
    """Return the stats shown after a progress bar."""

    data      = bar.format_dict
    n         = int(data["n"])
    total     = int(data["total"] or 0)
    elapsed   = data["elapsed"]
    rate      = data["rate"] or 0.0
    remaining = (total - n) / rate if rate else 0.0
    projected = elapsed + remaining

    fields = [
        f"{_clock(elapsed)}/{_clock(projected)}",
        f"{rate:.2f} {unit}/s",
    ]
    if created is not None:
        fields.append(f"jobs created: {created}")
    if updated is not None:
        fields.append(f"jobs updated: {updated}")
    if limiter is not None:
        fields.append(f"Workers: {limiter.limit}/{limiter.maximum}")
        fields.append(f"errors {limiter.errors}")
    else:
        if workers is not None:
            fields.append(f"Workers: {workers}/{workers}")
        if errors is not None:
            fields.append(f"errors {errors}")
    if throttle is not None:
        fields.append(f"throttle {throttle:.1f}s")
    return f"{label} {n}/{total} [" + ", ".join(fields) + "]"


def _set_plan_stats(bar, stats) -> None:
    """Refresh a planning bar with cumulative created/updated counts."""

    bar.set_postfix_str(_bar_stats(
        bar, "Stations", "station",
        created=stats["created"], updated=stats["updated"],
    ), refresh=True)


class _Bar(tqdm):
    """tqdm bar that removes the comma tqdm inserts before the postfix."""

    def __str__(self):
        return super().__str__().replace("|, ", "| ")


def _make_progress_bar(total: int, desc: str) -> _Bar:
    """Return a one-line progress bar, disabled without a terminal."""

    return _Bar(
        total=total, desc=desc,
        bar_format="{desc}: {percentage:3.0f}%|{bar}|{postfix}",
        disable=not _interactive(), file=sys.stderr, leave=True,
    )


def _print_job_header(job_config) -> None:
    """Print the job banner before its bars (terminal output only)."""

    if _interactive():
        tqdm.write(f"\r\n{job_config}:", file=sys.stderr)


def _announce(message: str, idle: bool = False) -> None:
    """Log an INFO line, or write it when idle on an interactive terminal."""

    if _interactive() and idle:
        tqdm.write(f"\r{message}", file=sys.stderr)
    elif not _interactive():
        logger.info(message)


def _yesterday() -> datetime:
    """Return yesterday at midnight."""

    return (datetime.now() - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _as_datetime(value, override=None):
    """Normalize a database or command-line date, leaving unknown values."""

    if override is not None:
        value = override
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return value


TELEMETRY_RANGES = {
    **{f"MINUTO_{minutes}": timedelta(minutes=minutes)
       for minutes in (5, 10, 15, 30)},
    **{f"HORA_{hours}": timedelta(hours=hours)
       for hours in range(1, 25)},
    **{f"DIAS_{days}": timedelta(days=days)
       for days in (2, 7, 14, 21, 30)},
}


def telemetry_range(remaining: timedelta) -> str:
    """Return the smallest range token that covers ``remaining``."""

    for token, duration in TELEMETRY_RANGES.items():
        if duration >= remaining:
            return token
    return "DIAS_30"


def telemetry_windows(start, end, active=False):
    """Return ``(Date, Range)`` windows for a station telemetry period.

    A midnight Fim is treated as inclusive dates. A Fim with a time uses the
    exact datetime difference, allowing HORA/MINUTO tails. An active station
    (null Fim) always uses DIAS_30. A sub-day range is only used for the final
    tail, because Data de Busca is date-only.
    """

    start = _as_datetime(start)
    end   = _as_datetime(end)
    windows = []
    if start is None or end is None or start > end:
        return windows

    current = start
    while current <= end:
        if active:
            token = "DIAS_30"
        elif end.time() == datetime.min.time():
            remaining = timedelta(days=(end.date() - current.date()).days + 1)
            token = telemetry_range(remaining)
        else:
            token = telemetry_range(end - current)
        step = TELEMETRY_RANGES[token]
        windows.append((current.date(), token))
        if step < timedelta(days=1):
            break
        current += step
    return windows


def _telemetry_station_windows(row, yesterday):
    """Return every ``(StationID, Date, Range)`` window for one station row."""

    station = row[0]
    start   = _as_datetime(row[1], CONFIG.INITIAL_DATE)
    end     = _as_datetime(row[2], CONFIG.FINAL_DATE)
    if start is None:
        return []
    if end is None:
        windows = telemetry_windows(start, yesterday, active=True)
    elif start > end:
        logger.debug(
            f"Telemetry: invalid period {start}..{end} for station {station}"
        )
        return []
    else:
        windows = telemetry_windows(start, end, active=False)
    return [(station, window_date, range_) for window_date, range_ in windows]


def _write_telemetry_jobs(plan, job_config):
    """Insert/update one bounded batch of telemetry windows."""

    station_ids = {station for station, _, _ in plan}
    existing = get_telemetry_job_keys(job_config, station_ids)

    new_jobs = []
    updates  = []
    for station, window_date, range_ in plan:
        current = existing.get((station, window_date))
        if current is None:
            new_jobs.append(TelemetryJobs(
                HidroTable = job_config,
                StationID  = station,
                Date       = datetime.combine(window_date, datetime.min.time()),
                Range      = range_,
                Status     = JobConfig.Status.PENDING.value,
                Retries    = 0,
            ))
            continue

        job_id, current_range = current
        if current_range != range_:
            updates.append({
                "ID":      job_id,
                "Range":   range_,
                "Status":  JobConfig.Status.PENDING.value,
                "Retries": 0,
            })

    if new_jobs:
        insert_jobs_bulk(new_jobs)
    if updates:
        update_job_mappings(job_config, updates)
    return len(new_jobs), len(updates)


def create_telemetry_jobs(stations, job_config, today=None) -> None:
    """Create or update the telemetry jobs for the given station rows.

    Stations are processed in bounded batches. A station is never split across
    batches, so the same ``(StationID, Date)`` window cannot be inserted twice.
    """

    yesterday  = (today or date.today()) - timedelta(days=1)
    chunk_size = _batch_size()
    stations   = list(stations)
    batch      = []
    stats      = {"created": 0, "updated": 0}

    bar = _make_progress_bar(len(stations), "Check")

    def flush():
        new, changed = _write_telemetry_jobs(batch, job_config)
        stats["created"] += new
        stats["updated"] += changed
        batch.clear()

    for row in stations:
        batch.extend(_telemetry_station_windows(row, yesterday))
        if len(batch) >= chunk_size:
            flush()
        bar.update(1)
        _set_plan_stats(bar, stats)

    if batch:
        flush()

    _set_plan_stats(bar, stats)
    bar.close()

    _announce(
        f"Telemetry: {stats['created']} new jobs, "
        f"{stats['updated']} updated jobs"
    )


def _telemetry_tail_rows(stations, existing, job_config):
    """Return due active-station rows that need newer telemetry windows."""

    active = [
        row for row in stations
        if row[0] in existing and row[2] is None
    ]
    if not active:
        return []

    bounds = get_telemetry_job_bounds(job_config, [row[0] for row in active])
    yesterday = date.today() - timedelta(days=1)
    rows = []
    for row in active:
        latest = bounds.get(row[0])
        if latest is None:
            rows.append(row)
            continue
        next_date = latest + TELEMETRY_RANGES["DIAS_30"]
        if next_date.date() <= yesterday:
            rows.append((row[0], latest, None))
    return rows


def check_telemetry_job(job_config: JobConfig) -> None:
    """Create/update telemetry jobs, then request the pending or failed ones.

    Stations without any job get a full plan. Existing stations are only
    reconciled when a date window was requested, otherwise only active
    stations receive new tail windows once the latest one is exhausted.
    """

    stations = get_telemetry_stations(CONFIG.STATIONS or None)
    existing = get_station_ids(job_config, CONFIG.STATIONS)
    planning = [row for row in stations if row[0] not in existing]

    if existing and (CONFIG.INITIAL_DATE is not None or
                     CONFIG.FINAL_DATE is not None):
        planning.extend(row for row in stations if row[0] in existing)
    elif existing:
        planning.extend(_telemetry_tail_rows(stations, existing, job_config))

    if planning:
        create_telemetry_jobs(planning, job_config)

    trigger_jobs(job_config)


_token_cache: Optional[Token] = None
"""Private Token global to control expiration time."""

_limiter: Optional[_AdaptiveLimiter] = None
"""Active adaptive concurrency limiter for the current request phase."""

_throttle_until = 0.0
"""Monotonic time before which no new request should be made after a throttle."""

_request_error_lock = Lock()
_request_errors = 0
"""API failures observed while reading cached payloads this run."""


def _reset_request_errors() -> None:
    """Clear the per-request-phase API failure counter."""

    global _request_errors
    with _request_error_lock:
        _request_errors = 0


def _record_request_error() -> None:
    """Count an API failure when ``--read-json`` falls back to the network."""

    if not CONFIG.READ_JSON:
        return
    global _request_errors
    with _request_error_lock:
        _request_errors += 1


def _request_error_count() -> int:
    """Return the API failures counted in the current request phase."""

    with _request_error_lock:
        return _request_errors


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
            _announce(f"No pending jobs for {job_config}.", idle=True)


def check_series_job(job_config: JobConfig) -> None:
    """Checks an JobConfig.
    Create missing station jobs and start pending jobs requisition.
    """

    selected    = set(CONFIG.STATIONS)
    period_data = []
    for data in get_period(job_config).all():
        if selected and data[0] not in selected:
            continue
        start = _as_datetime(data[1], CONFIG.INITIAL_DATE)
        end   = _as_datetime(data[2], CONFIG.FINAL_DATE)
        period_data.append((data[0], start, end))

    if selected:
        missing_stations = selected - {data[0] for data in period_data}
        if missing_stations:
            logger.warning(
                f"No period data for stations {sorted(missing_stations)} "
                f"in {job_config}."
            )

    existing = get_station_ids(job_config, CONFIG.STATIONS)
    missing  = [data for data in period_data if data[0] not in existing]
    reconcile = []
    if CONFIG.INITIAL_DATE is not None or CONFIG.FINAL_DATE is not None:
        reconcile = [data for data in period_data if data[0] in existing]

    planning = missing + reconcile
    if planning:
        stats = {"created": 0, "updated": 0}
        bar   = _make_progress_bar(len(planning), "Check")
        if missing:
            _announce(
                f"Creating jobs from {len(missing)} stations for {job_config}"
            )
            create_series_jobs(missing, job_config, bar=bar, stats=stats)
        if reconcile:
            update_series_job_windows(
                job_config, reconcile, bar=bar, stats=stats,
            )
        _set_plan_stats(bar, stats)
        bar.close()

    if CONFIG.FINAL_DATE is None:
        update_series_job(job_config)
    trigger_jobs(job_config, SERIES_RETRY_DEPTH)


def trigger_jobs(job_config: JobConfig, retry_depth: int = 0) -> None:
    """Trigger pending and failed jobs, optionally retrying within the run."""

    status = [JobConfig.Status.FAILED.value, JobConfig.Status.PENDING.value]
    filters = create_job_filters(job_config, status, last_check=False,
                                 stations=CONFIG.STATIONS, max_retries=True,
                                 initial_date=CONFIG.INITIAL_DATE,
                                 final_date=CONFIG.FINAL_DATE)
    count = count_job(job_config, filters)
    if not count:
        _announce(f"No pending jobs for {job_config}.", idle=True)
        return

    for attempt in range(retry_depth + 1):
        _announce(f"Initiating {count} jobs for {job_config}")
        trigger_job(job_config, filters, count)
        if attempt == retry_depth:
            break
        count = count_job(job_config, filters)
        if not count:
            return

    if retry_depth:
        remaining = count_job(job_config, filters)
        if remaining:
            logger.warning(
                f"{remaining} jobs for {job_config} remain pending/failed "
                f"after {retry_depth} same-run retries; leaving them for the "
                f"next run."
            )


def create_series_jobs(stations_data: List, job_config: JobConfig,
                       bar=None, stats=None) -> int:
    """ Creates Series Jobs for each station received for a given JobConfig.
    Preprocess all years from "Start Date" to "End Date" that will become a job request.
    Jobs are written in bounded chunks to keep memory flat.

    ``bar`` and ``stats`` may be shared with the date-window reconciliation step
    so one Check bar reports both created and updated jobs.
    """
    start         = time.time()
    stations_data = list(stations_data)
    chunk_size    = max(_batch_size(), BULK_SIZE)
    workers       = min(max(1, CONFIG.MAX_WORKERS), os.cpu_count() or 1)
    workers       = min(workers, max(1, len(stations_data)))
    batch         = []
    created       = 0
    own_bar       = bar is None
    if stats is None:
        stats = {"created": 0, "updated": 0}
    if bar is None:
        bar = _make_progress_bar(len(stations_data), "Check")

    def collect(future):
        nonlocal created
        try:
            processed_jobs = future.result()
        except Exception as e:
            logger.error(f"Error processing period: {e}")
            processed_jobs = []
        batch.extend(processed_jobs)
        if len(batch) >= chunk_size:
            insert_jobs_bulk(batch)
            created += len(batch)
            stats["created"] += len(batch)
            batch.clear()
        bar.update(1)
        _set_plan_stats(bar, {
            "created": stats["created"] + len(batch),
            "updated": stats["updated"],
        })

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
        stats["created"] += len(batch)

    _set_plan_stats(bar, stats)
    if own_bar:
        bar.close()

    elapsed = time.time() - start
    _announce(f"Created {created} jobs for {job_config} in {elapsed:.2f} seconds")
    return created


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


def _reconcile_jobs(jobs, desired_jobs):
    """Return ``(updates, new_jobs)`` for one station's desired windows."""

    updates, new_jobs = [], []
    for desired in desired_jobs:
        window = (desired.FromDate, desired.ToDate)
        exact = next((job for job in jobs
                      if (job.FromDate, job.ToDate) == window), None)
        if exact is not None:
            jobs.remove(exact)
            continue

        overlap = next((job for job in jobs
                        if job.FromDate < desired.ToDate and
                           job.ToDate > desired.FromDate), None)
        if overlap is None:
            new_jobs.append(desired)
            continue

        jobs.remove(overlap)
        updates.append({
            "ID":       overlap.ID,
            "FromDate": desired.FromDate,
            "ToDate":   desired.ToDate,
            "Status":   desired.Status,
            "Retries":  0,
        })
    return updates, new_jobs


def update_series_job_windows(job_config: JobConfig, stations_data,
                              bar=None, stats=None):
    """Reconcile existing series jobs with the requested station windows.

    Jobs whose dates already match a desired yearly window are kept
    untouched. When a window changed, an overlapping job is reused and its
    dates are updated; if no overlap exists, a new job is inserted. Jobs
    outside the requested interval are kept but are not queued for this run
    (see :func:`create_job_filters`).

    ``bar`` and ``stats`` may be shared with missing-job creation so one Check
    bar reports both created and updated jobs.
    """

    stations_data = list(stations_data)
    if not stations_data:
        return 0, 0

    start_time = time.time()
    chunk_size = _batch_size()
    updated    = 0
    inserted   = 0
    own_bar    = bar is None
    if stats is None:
        stats = {"created": 0, "updated": 0}
    if bar is None:
        bar = _make_progress_bar(len(stations_data), "Check")

    for station_chunk in _chunked(stations_data, chunk_size):
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
        stats["updated"] += len(updates)

        for job_chunk in _chunked(new_jobs, chunk_size):
            insert_jobs_bulk(job_chunk)
        inserted += len(new_jobs)
        stats["created"] += len(new_jobs)

        bar.update(len(station_chunk))
        _set_plan_stats(bar, stats)

    _set_plan_stats(bar, stats)
    if own_bar:
        bar.close()

    elapsed = time.time() - start_time
    _announce(
        f"Updated {updated} and inserted {inserted} jobs for {job_config} "
        f"in {elapsed:.2f} seconds"
    )
    return updated, inserted


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
    """Request every pending or failed job of one JobConfig.

    Jobs are streamed in pages and only a bounded number of futures is kept in
    flight. The queue is bounded so slow writes apply backpressure to workers.
    A tqdm bar reports jobs completed against ``total`` on a terminal; when
    output is redirected the writer's throttled heartbeat lines report progress
    instead.

    Network runs use an adaptive in-flight limiter so the API is not bursted.
    """

    batch_size = _batch_size()
    workers    = max(1, CONFIG.MAX_WORKERS)
    global _limiter
    workers = min(workers, _thread_limit())
    workers = min(workers, max(1, total))
    if CONFIG.READ_JSON:
        _limiter = None
    else:
        _limiter = _AdaptiveLimiter(
            initial=min(workers, ADAPTIVE_INITIAL), maximum=workers
        )
    limiter = _limiter
    write_queue.maxsize = batch_size
    _reset_request_errors()

    bar = _make_progress_bar(total, "Request")
    interactive = not bar.disable

    def refresh_stats(active_limiter, throttle=None):
        bar.set_postfix_str(_bar_stats(
            bar, "Jobs", "job", limiter=active_limiter,
            workers=workers if active_limiter is None else None,
            errors=_request_error_count() if active_limiter is None else None,
            throttle=throttle,
        ), refresh=True)

    refresh_stats(limiter)

    last_stats = 0.0

    def tick(done):
        """Refresh stats on real changes (or once a second) and the throttle."""

        nonlocal last_stats
        now = time.monotonic()
        remaining = 0.0
        if limiter is not None:
            remaining = limiter.pause_until - now
        throttled = remaining > 0
        if done or throttled or now - last_stats >= 1.0:
            refresh_stats(limiter, remaining if throttled else None)
            last_stats = now

    def finish(done):
        for future in done:
            _report_future(future)
            bar.update(1)
        tick(done)

    writer = Thread(target=db_writer, args=(interactive,), daemon=True)
    writer.start()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = set()
        for job in iter_jobs(job_config, filters, batch_size):
            pending.add(executor.submit(handle_job_request, job, job_config))
            if len(pending) >= 2 * workers:
                done, pending = wait(
                    pending, timeout=0.1, return_when=FIRST_COMPLETED
                )
                finish(done)

        while pending:
            done, pending = wait(
                pending, timeout=0.1, return_when=FIRST_COMPLETED
            )
            finish(done)

    _limiter = None

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

    refresh_stats(limiter)
    bar.close()
    if interactive:
        print(f"\rRequest status: [{summary}]", file=sys.stderr)
    else:
        _announce(summary)


token_lock = Lock()


def _mark_failed(job: HidroJob, job_config: JobConfig) -> None:
    """Mark a job FAILED and, for series jobs, bump its retry count."""

    job.Status = JobConfig.Status.FAILED.value
    match job_config:
        case JobConfig.Series() | JobConfig.Telemetry():
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


def _throttle() -> None:
    """Slow the request pool after the API rejects or rate-limits a request."""

    global _throttle_until
    if _limiter is not None:
        _limiter.throttled()
        _throttle_until = max(_throttle_until, _limiter.pause_until)
    else:
        _throttle_until = max(
            _throttle_until, time.monotonic() + ADAPTIVE_PAUSE
        )


def _wait_throttle() -> None:
    """Sleep while a throttle pause from an earlier request is still active."""

    remaining = _throttle_until - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def _handle_http_error(job: HidroJob, job_config: JobConfig, e) -> bool:
    """Apply an HTTPError to the job. Return True when the job is skipped."""

    code = e.response.status_code if e.response is not None else None
    if code == 401:
        logger.verbose(f"[WORKER JOB {job.ID}]: Unauthorized, skipping.")
        return True
    if code == 429:
        _throttle()
        logger.warning(f"[WORKER JOB {job.ID}]: Rate limited, retrying later.")
        return True
    if code is not None and 500 <= code < 600:
        _throttle()
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
            case JobConfig.Series() | JobConfig.Telemetry():
                if items:
                    items = validate_series_items(job, job_config, items)
                if items and isinstance(job_config, JobConfig.Series):
                    items = validate_series_items_date(job, job_config, items)
    except Exception as e:
        logger.error(f"[WORKER JOB {job.ID}]: {e}, {items}, {type(items)}")
    return items


def handle_job_request(job: HidroJob, job_config: JobConfig) -> None:
    """Request one job, validate it and enqueue the result.

    Skips the write for unauthorized or transient request errors, leaving the
    job PENDING so a later run retries it.
    """

    start = time.time()
    success, items = False, []
    _wait_throttle()
    limiter = _limiter
    try:
        with token_lock:
            token = get_token()
        if limiter is not None:
            limiter.acquire()
        try:
            success, items = request_job_data(
                job_config, token, job.to_params(CONFIG.FILTER),
                save_json = CONFIG.SAVE_JSON,
                json_dir  = CONFIG.JSON_DIR,
                read_json = CONFIG.READ_JSON,
            )
        finally:
            if limiter is not None:
                limiter.release()
        if limiter is not None:
            limiter.success()
    except HTTPError as e:
        _record_request_error()
        if _handle_http_error(job, job_config, e):
            return
    except Timeout as e:
        _record_request_error()
        _throttle()
        logger.verbose(
            f"[WORKER JOB {job.ID}]: request timed out, retrying later. {e}"
        )
        return
    except RequestException as e:
        _record_request_error()
        logger.trace(f"[WORKER JOB {job.ID}]: Request error, skipping. {e}")
        return
    except Exception as e:
        _record_request_error()
        logger.error(f"[WORKER JOB {job.ID}]: unhandled error: {e}")
        _mark_failed(job, job_config)
    else:
        if success:
            items = _process_success(job, job_config, items)
        else:
            _record_request_error()
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
    flush_at    = max(CONFIG.BATCH_SIZE, BULK_SIZE)
    failed      = None

    while True:
        try:
            job_config, job, data, worker_time, stop_signal = write_queue.get()

            # After a write failure, keep draining so producers do not block
            # forever on the bounded queue, then stop on the finish signal.
            if failed is not None:
                if stop_signal:
                    break
                continue

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

            if (len(batch_buffer["data"]) >= flush_at or
                len(batch_buffer["jobs"]) >= flush_at or stop_signal):
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
            failed = e
            logger.error(f"[WRITER]: db_writer exception: {e}")

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


def _water_quality_status_items(items):
    """Attach each item's ``QualAguaID`` and keep rows with a resolved parent."""

    lookup = get_qual_agua_ids(items)

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

    if items:
        filtered_items = items
        if not isinstance(job_config, JobConfig.Base):
            filtered_items = filter_repeated_series_items(job_config, items)

        upsert_items(job_config, filtered_items)
        parent_ids = (get_registro_ids(str(job_config), filtered_items)
                      if job_config == JobConfig.Series.CROSS_SECTION else None)
        _record_provenance(job_config, job_config, filtered_items, parent_ids)

        if job_config == JobConfig.Series.WATER_QUALITY:
            status_items = _water_quality_status_items(filtered_items)
            if status_items:
                upsert_items(f'{job_config}Status', status_items)
                _record_provenance(job_config, f'{job_config}Status', status_items)

        elif job_config == JobConfig.Series.CROSS_SECTION:
            # Levels live in the raw items; parent rows are deduplicated.
            vertical_items, vertical_entries = _vertical_cross_section_entries(
                items, filtered_items, parent_ids)
            if vertical_entries:
                inserted = insert_hidro(vertical_entries, expire=False)
                _record_provenance(
                    job_config, "PerfilTransversalVert", vertical_items,
                    [entry.RegistroID for entry in inserted],
                )

    if jobs:
        update_jobs(jobs, job_config)
        logger.trace(f"[WRITER {job_config}]: Updated {len(jobs)} jobs")
    return time.perf_counter() - start_time


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


def run(config: Config):
    """Run every base and series job using ``config``."""

    global CONFIG
    CONFIG = config
    rule = "-" * 40 + "\n"  # trailing newline leaves a blank line for navigation

    for job in JobConfig.Base:
        _announce(rule)
        _print_job_header(job)
        check_base_job(job)

    if CONFIG.SKIP_SERIES_JOBS:
        _announce(rule)
        _announce("Skiping series and telemetry jobs.")
        return

    for job in (*JobConfig.Series, *JobConfig.Telemetry):
        _announce(rule)
        if (job in CONFIG.SKIP_FOR or
                (len(CONFIG.RUN_FOR) > 0 and job not in CONFIG.RUN_FOR)):
            _announce(f"Skiping job for {job}.")
            continue
        _print_job_header(job)
        (check_telemetry_job if isinstance(job, JobConfig.Telemetry)
         else check_series_job)(job)

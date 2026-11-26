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

import pytest
from unittest.mock import patch, MagicMock

import io
import logging
import time

from datetime import datetime, timedelta
from queue import Queue

from requests.exceptions import ReadTimeout

import hidrocli.jobs.runner
from hidrocli.config import setup_logger

setup_logger()


def _set_config(monkeypatch, **kwargs):
    """Replace the runner's frozen CONFIG with one field updated."""
    monkeypatch.setattr(
        hidrocli.jobs.runner, "CONFIG",
        hidrocli.jobs.runner.CONFIG._replace(**kwargs),
    )


def _http_error(status, body=None):
    """Build an HTTPError whose response carries ``status`` and optional body."""
    response = MagicMock(status_code=status)
    if body is not None:
        response.json.return_value = body
    return hidrocli.jobs.runner.HTTPError(f"{status}", response=response)


SQL_GRAMMAR_BODY = {
    "status":  "EXPECTATION_FAILED",
    "code":    417,
    "message": "org.hibernate.exception.SQLGrammarException: could not extract ResultSet",
    "items":   None,
}


@patch('hidrocli.jobs.runner.count_client')
@patch('hidrocli.jobs.runner.add_token')
@patch('hidrocli.jobs.runner.update_token')
@patch('hidrocli.jobs.runner.get_credentials')
@patch('hidrocli.jobs.runner.request_token')
@patch('hidrocli.jobs.runner.get_token_model')
def test_get_token_add_new_token(mock_model,  mock_request, mock_creds,
                                 mock_update, mock_add,     mock_count):
    mock_model.return_value   = None
    mock_creds.return_value   = MagicMock(ID="test_id", Password="test_pass")
    mock_request.return_value = ("new_token", datetime.now() + timedelta(hours=1))
    mock_count.return_value   = 0

    result = hidrocli.jobs.runner.get_token()

    mock_model.assert_called_once()
    mock_creds.assert_called_once()
    mock_request.assert_called_once_with("test_id", "test_pass")
    mock_count.assert_called_once()
    mock_update.assert_not_called()
    mock_add.assert_called_once()

    assert result == "new_token"

@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.insert_jobs')
@patch('hidrocli.jobs.runner.count_job')
@pytest.mark.parametrize("job_config", [
    hidrocli.jobs.runner.JobConfig.Base.BASIN,
    hidrocli.jobs.runner.JobConfig.Base.SUB_BASIN,
    hidrocli.jobs.runner.JobConfig.Base.ENTITY,
    hidrocli.jobs.runner.JobConfig.Base.TOWNSHIP,
    hidrocli.jobs.runner.JobConfig.Base.RIVER,
    hidrocli.jobs.runner.JobConfig.Base.STATE,
])
def test_check_base_job(mock_count_jobs, mock_insert_jobs, mock_trigger_job, job_config):
    """TODO"""

    mock_count_jobs.side_effect = [0, 1, 1, 1, 0]
    hidrocli.jobs.runner.check_base_job(job_config)
    mock_insert_jobs.assert_called_once()
    mock_trigger_job.assert_called_once()


CORRUPTED_DATES_PARAMS = [
    (3154001, "2911-12-01 00:00:00", "2026-07-01 00:00:00", 4),
    (1048002, "1996-12-01 00:00:00", "1977-11-01 00:00:00", 4),
    (1740000, "2009-01-02 00:00:00", "2009-01-01 00:00:00", 4),
    (849001,  "1996-12-01 00:00:00", "1985-03-01 00:00:00", 4),
    (650000,  "1996-12-01 00:00:00", "1982-01-01 00:00:00", 4),
    (1748006, "1980-09-01 00:00:00", "1980-01-01 00:00:00", 4),
    (1036042, "1982-09-01 00:00:00", "1973-01-01 00:00:00", 4),
    (338025,  "1977-03-01 00:00:00", "1931-02-01 00:00:00", 4),
    (2652043, "1989-07-01 00:00:00", "1987-08-01 00:00:00", 4),
    (2950036, "1966-01-02 00:00:00", "1966-01-01 00:00:00", 4),
    (2056005, "2018-01-02 00:00:00", "2018-01-01 00:00:00", 4),
]

@pytest.mark.parametrize("station_code, start_date, end_date, expected_status", CORRUPTED_DATES_PARAMS)
def test_process_period_returns_corrupted_for_invalid_dates(station_code, start_date, end_date, expected_status):
    """Test that process_period returns CORRUPTED status when FromDate > ToDate."""

    from hidrocli.jobs.runner import JobConfig, process_period
    result = process_period(station_code, start_date, end_date, JobConfig.Series.RAIN)

    assert len(result) == 1, f"Expected 1 job, got {len(result)}"
    assert result[0].Status == expected_status, \
        f"Expected status {expected_status}, got {result[0].Status}"
    assert result[0].StationID == station_code
    assert result[0].FromDate  == datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S")
    assert result[0].ToDate    == datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")


def test_process_period_returns_corrupted_for_future_date():
    """Test that future start date returns CORRUPTED."""

    from hidrocli.jobs.runner import JobConfig, process_period
    future_date = (datetime.today() + timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S")
    result = hidrocli.jobs.runner.process_period(123456, future_date, "2020-01-01 00:00:00", JobConfig.Series.RAIN)

    assert len(result) == 1
    assert result[0].Status == 4


@pytest.mark.parametrize("start_date, end_date", [
    ("1970-09-01 00:00:00", "1970-12-01 00:00:00"),
    ("1970-09-01 00:00:00", "1970-09-01 00:00:00"),
])
def test_process_period_creates_same_year_job(start_date, end_date):
    """Periods shorter than a year must still produce one job."""

    from hidrocli.jobs.runner import JobConfig, process_period
    result = process_period(123456, start_date, end_date, JobConfig.Series.RAIN)

    assert len(result) == 1
    assert result[0].Status == JobConfig.Status.PENDING.value
    assert result[0].FromDate == datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S")
    assert result[0].ToDate   == datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")


def _load_json_file(job_config):
    with open(f'./tests/fixtures/{job_config}.json') as f:
        import json;
        return json.load(f)


@pytest.mark.parametrize("job_config", [
    hidrocli.jobs.runner.JobConfig.Series.RAIN,
])
def test_filter_repeated_series_items(job_config):
    items = hidrocli.jobs.runner.normalize_items(str(job_config), _load_json_file(job_config))
    filtered = hidrocli.jobs.runner.filter_repeated_series_items(job_config, items)
    assert len(items) != len(filtered)


@patch('hidrocli.jobs.runner.process_period')
def test_create_series_jobs_inserts_in_chunks(mock_period, monkeypatch):
    _set_config(monkeypatch, MAX_WORKERS=2, BATCH_SIZE=3)
    monkeypatch.setattr(hidrocli.jobs.runner, "BULK_SIZE", 3)

    def fake_period(station, start, end, job_config):
        return [
            hidrocli.jobs.runner.SeriesJobs(
                HidroTable=job_config,
                StationID=station,
                FromDate=datetime(2020, 1, 1),
                ToDate=datetime(2021, 1, 1),
                Status=1,
            )
            for _ in range(2)
        ]

    mock_period.side_effect = fake_period

    chunks = []
    monkeypatch.setattr(
        hidrocli.jobs.runner, "insert_jobs_bulk",
        lambda jobs: chunks.append(len(jobs)),
    )

    stations = [
        [station, "2020-01-01 00:00:00", "2021-01-01 00:00:00"]
        for station in range(1, 6)
    ]
    hidrocli.jobs.runner.create_series_jobs(
        stations, hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    assert sum(chunks) == 10
    assert len(chunks) > 1
    assert all(size <= 4 for size in chunks)


@patch('hidrocli.jobs.runner.count_job_by_status', return_value=[])
@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.db_writer')
@patch('hidrocli.jobs.runner.handle_job_request')
@patch('hidrocli.jobs.runner.iter_jobs')
def test_trigger_job_streams_jobs(mock_iter, mock_handle, mock_writer,
                                  mock_queue, mock_count, monkeypatch):
    mock_iter.return_value = iter([
        MagicMock(ID=index) for index in range(20)
    ])
    _set_config(monkeypatch, MAX_WORKERS=2, BATCH_SIZE=5)

    hidrocli.jobs.runner.trigger_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, ["filter"], 20
    )

    assert mock_handle.call_count == 20
    mock_iter.assert_called_once_with(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, ["filter"], 5
    )
    mock_queue.put.assert_called_once()


@patch('hidrocli.jobs.runner.count_job_by_status', return_value=[])
@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.db_writer')
@patch('hidrocli.jobs.runner._make_progress_bar')
@patch('hidrocli.jobs.runner._AdaptiveLimiter')
@patch('hidrocli.jobs.runner.handle_job_request')
@patch('hidrocli.jobs.runner.iter_jobs')
def test_trigger_job_caps_limiter_to_total(
        mock_iter, mock_handle, mock_limiter_cls, mock_bar,
        mock_writer, mock_queue, mock_count, monkeypatch):
    mock_iter.return_value = iter([MagicMock(ID=1)])
    bar = mock_bar.return_value
    bar.disable = False
    bar.format_dict = {"n": 0, "total": 1, "elapsed": 0, "rate": None}
    limiter = mock_limiter_cls.return_value
    limiter.pause_until = 0.0

    _set_config(monkeypatch, MAX_WORKERS=256, BATCH_SIZE=5, READ_JSON=False)

    hidrocli.jobs.runner.trigger_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, [], 1
    )

    _, kwargs = mock_limiter_cls.call_args
    assert kwargs["initial"] == 1
    assert kwargs["maximum"] == 1


def test_adaptive_limiter_grows_and_halves():
    limiter = hidrocli.jobs.runner._AdaptiveLimiter(initial=4, maximum=8)

    assert limiter.limit == 4
    assert limiter.slow_start is True

    # Slow start doubles the limit once a full window succeeds.
    for _ in range(4):
        limiter.success()
    assert limiter.limit == 8

    limiter.success()
    assert limiter.limit == 8

    # A throttle halves and switches to additive growth.
    limiter.throttled()
    assert limiter.limit == 4
    assert limiter.slow_start is False
    assert limiter.pause_until > 0

    for _ in range(hidrocli.jobs.runner.ADAPTIVE_INCREASE_AFTER):
        limiter.success()
    assert limiter.limit == 5


def test_throttle_sets_persistent_pause(monkeypatch):
    monkeypatch.setattr(hidrocli.jobs.runner, "_limiter", None)
    monkeypatch.setattr(hidrocli.jobs.runner, "_throttle_until", 0.0)

    hidrocli.jobs.runner._throttle()

    assert hidrocli.jobs.runner._throttle_until > time.monotonic()


@patch('hidrocli.jobs.runner.time.sleep')
def test_wait_throttle_sleeps(mock_sleep, monkeypatch):
    monkeypatch.setattr(
        hidrocli.jobs.runner, "_throttle_until",
        time.monotonic() + 10,
    )

    hidrocli.jobs.runner._wait_throttle()

    mock_sleep.assert_called_once()


def test_progress_renders_bar_stats_and_throttle(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(hidrocli.jobs.runner, "_interactive", lambda: True)
    monkeypatch.setattr(hidrocli.jobs.runner.sys, "stderr", stream)

    limiter = hidrocli.jobs.runner._AdaptiveLimiter(initial=4, maximum=8)
    limiter.limit = 8
    limiter.errors = 2
    limiter.pause_until = time.monotonic() + 1.0

    bar = hidrocli.jobs.runner._make_progress_bar(1, "Request")
    bar.update(1)
    bar.set_postfix_str(hidrocli.jobs.runner._bar_stats(
        bar, "Jobs", "job", limiter=limiter, throttle=1.0
    ), refresh=True)
    bar.close()

    output = stream.getvalue()
    assert "Request:" in output
    assert "Jobs 1/1" in output
    assert "limiter 8/8" not in output
    assert "Workers: 8/8" in output
    assert "errors 2" in output
    assert "throttle 1.0s" in output


def test_bar_stats_shows_updated_and_static_workers():
    bar = MagicMock()
    bar.format_dict = {
        "n": 1, "total": 1, "elapsed": 0, "rate": None,
    }

    text = hidrocli.jobs.runner._bar_stats(
        bar, "Stations", "station", created=2, updated=3, workers=4, errors=2,
    )

    assert "jobs created: 2" in text
    assert "jobs updated: 3" in text
    assert "Workers: 4/4" in text
    assert "errors 2" in text


@patch('hidrocli.jobs.runner.count_job_by_status', return_value=[])
@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.db_writer')
@patch('hidrocli.jobs.runner._bar_stats', return_value="")
@patch('hidrocli.jobs.runner._AdaptiveLimiter')
@patch('hidrocli.jobs.runner._make_progress_bar')
@patch('hidrocli.jobs.runner.handle_job_request')
@patch('hidrocli.jobs.runner.iter_jobs')
def test_trigger_job_read_json_shows_static_workers(
        mock_iter, mock_handle, mock_bar_factory, mock_limiter_cls,
        mock_stats, mock_writer, mock_queue, mock_count, monkeypatch):
    mock_iter.return_value = iter([MagicMock(ID=index) for index in range(4)])
    bar = mock_bar_factory.return_value
    bar.disable = True
    monkeypatch.setattr(hidrocli.jobs.runner, "_thread_limit", lambda: 8)
    _set_config(monkeypatch, MAX_WORKERS=4, BATCH_SIZE=5, READ_JSON=True)

    hidrocli.jobs.runner.trigger_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, [], 4
    )

    mock_limiter_cls.assert_not_called()
    assert mock_stats.call_args.kwargs["limiter"] is None
    assert mock_stats.call_args.kwargs["workers"] == 4
    assert mock_stats.call_args.kwargs["errors"] == 0
    for call in mock_stats.call_args_list:
        assert call.kwargs["limiter"] is None
        assert call.kwargs["workers"] == 4
        assert call.kwargs["errors"] == 0


def _writer_message(job_config, *, job=None, items=None, worker_time=0.0,
                    stop_signal=False):
    """Build one queue item consumed by the writer thread."""

    return hidrocli.jobs.runner.QueueData(
        job_config=job_config,
        job=job,
        items=items,
        worker_time=worker_time,
        stop_signal=stop_signal,
    )


def _drain_writer(monkeypatch, messages, *, interactive=False, write=None):
    """Run ``db_writer`` to completion over preloaded queue messages."""

    queue = Queue()
    for message in messages:
        queue.put(message)

    calls = []
    if write is None:
        def write(job_config, jobs, items):
            calls.append((job_config, list(jobs), list(items)))
            return 0.0

    monkeypatch.setattr(hidrocli.jobs.runner, "write_queue", queue)
    monkeypatch.setattr(hidrocli.jobs.runner, "write_data", write)
    hidrocli.jobs.runner.db_writer(interactive=interactive)

    assert queue.unfinished_tasks == 0
    return calls


def test_db_writer_flushes_batched_jobs_and_data(monkeypatch):
    config = hidrocli.jobs.runner.JobConfig.Series.RAIN
    job = MagicMock()
    first = {"RegistroID": 1}
    second = {"RegistroID": 2}

    calls = _drain_writer(monkeypatch, [
        _writer_message(config, job=job, items=[first], worker_time=0.4),
        _writer_message(config, items=[second], worker_time=0.2),
        _writer_message(config, stop_signal=True),
    ])

    assert calls == [(config, [job], [first, second])]


def test_db_writer_flushes_at_bulk_threshold(monkeypatch):
    config = hidrocli.jobs.runner.JobConfig.Series.RAIN
    _set_config(monkeypatch, BATCH_SIZE=1)
    monkeypatch.setattr(hidrocli.jobs.runner, "BULK_SIZE", 1)
    first_job, second_job = MagicMock(), MagicMock()

    calls = _drain_writer(monkeypatch, [
        _writer_message(config, job=first_job, items=[{"ID": 1}]),
        _writer_message(config, job=second_job, items=[{"ID": 2}]),
        _writer_message(config, stop_signal=True),
    ])

    assert calls == [
        (config, [first_job], [{"ID": 1}]),
        (config, [second_job], [{"ID": 2}]),
        (config, [], []),
    ]


def test_db_writer_non_interactive_logs_progress_and_summary(
        monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="hidrocli.jobs.runner")
    monkeypatch.setattr(hidrocli.jobs.runner, "PROGRESS_INTERVAL", 0.0)
    config = hidrocli.jobs.runner.JobConfig.Series.RAIN

    calls = _drain_writer(monkeypatch, [
        _writer_message(config, items=[{"ID": 1}], worker_time=0.5),
        _writer_message(config, stop_signal=True),
    ])

    assert calls == [(config, [], [{"ID": 1}])]
    messages = [record.getMessage() for record in caplog.records]
    assert any("1 rows, 0 jobs" in message for message in messages)
    assert any(
        "worker /" in message and "writer" in message for message in messages
    )


def test_db_writer_interactive_skips_progress_logs(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="hidrocli.jobs.runner")
    monkeypatch.setattr(hidrocli.jobs.runner, "PROGRESS_INTERVAL", 0.0)
    config = hidrocli.jobs.runner.JobConfig.Series.RAIN

    _drain_writer(
        monkeypatch,
        [
            _writer_message(config, items=[{"ID": 1}], worker_time=0.5),
            _writer_message(config, stop_signal=True),
        ],
        interactive=True,
    )

    assert [
        record for record in caplog.records
        if record.name == "hidrocli.jobs.runner"
        and record.levelno >= logging.INFO
    ] == []


def test_db_writer_drains_after_write_failure(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="hidrocli.jobs.runner")
    config = hidrocli.jobs.runner.JobConfig.Series.RAIN
    _set_config(monkeypatch, BATCH_SIZE=1)
    monkeypatch.setattr(hidrocli.jobs.runner, "BULK_SIZE", 1)
    attempts = []

    def broken_write(job_config, jobs, items):
        attempts.append((job_config, list(jobs), list(items)))
        raise RuntimeError("disk full")

    calls = _drain_writer(
        monkeypatch,
        [
            _writer_message(config, items=[{"ID": 1}]),
            _writer_message(config, items=[{"ID": 2}]),
            _writer_message(config, stop_signal=True),
        ],
        write=broken_write,
    )

    assert calls == []
    assert attempts == [(config, [], [{"ID": 1}])]
    assert "disk full" in caplog.text


@patch('hidrocli.jobs.runner.trigger_jobs')
@patch('hidrocli.jobs.runner.update_series_job')
@patch('hidrocli.jobs.runner.update_series_job_windows')
@patch('hidrocli.jobs.runner.create_series_jobs')
@patch('hidrocli.jobs.runner.get_station_ids', return_value={2})
@patch('hidrocli.jobs.runner.get_period')
def test_check_series_job_unifies_created_and_updated_counts(
        mock_period, mock_station_ids, mock_create, mock_update_windows,
        mock_update, mock_trigger, monkeypatch):
    mock_period.return_value.all.return_value = [
        (1, datetime(2000, 1, 1), datetime(2010, 1, 1)),
        (2, datetime(2001, 1, 1), datetime(2011, 1, 1)),
    ]
    _set_config(
        monkeypatch,
        STATIONS=[], INITIAL_DATE=datetime(2005, 1, 1),
        FINAL_DATE=datetime(2008, 1, 1),
    )

    def fake_create(rows, job_config, bar=None, stats=None):
        stats["created"] += len(rows)
        return len(rows)

    def fake_update(job_config, rows, bar=None, stats=None):
        stats["updated"] += 2
        return 2, 0

    mock_create.side_effect = fake_create
    mock_update_windows.side_effect = fake_update

    descs = []
    stats_calls = []
    bar = MagicMock()
    monkeypatch.setattr(
        hidrocli.jobs.runner, "_make_progress_bar",
        lambda total, desc: descs.append(desc) or bar,
    )
    monkeypatch.setattr(
        hidrocli.jobs.runner, "_bar_stats",
        lambda *args, **kwargs: stats_calls.append(kwargs) or "",
    )

    hidrocli.jobs.runner.check_series_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    assert descs == ["Check"]
    assert stats_calls[-1]["created"] == 1
    assert stats_calls[-1]["updated"] == 2
    bar.close.assert_called_once()


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data')
@patch('hidrocli.jobs.runner.get_token')
@pytest.mark.parametrize("save_json", [True, False])
@pytest.mark.parametrize("read_json", [True, False])
def test_handle_job_request_passes_json_flags(
        mock_token, mock_request, mock_queue,
        monkeypatch, save_json, read_json):
    _set_config(monkeypatch, SAVE_JSON=save_json, READ_JSON=read_json, JSON_DIR="custom/json")
    mock_request.return_value = (True, [])
    job = MagicMock()
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(
        job, hidrocli.jobs.runner.JobConfig.Base.BASIN
    )

    assert mock_request.call_args.kwargs == {
        "save_json": save_json,
        "json_dir":  "custom/json",
        "read_json": read_json,
    }


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data')
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_tags_items_with_job_id(
        mock_token, mock_request, mock_queue):
    items = [{"codigoestacao": 1}]
    mock_request.return_value = (True, items)
    job = MagicMock()
    job.ID = 42
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(
        job, hidrocli.jobs.runner.JobConfig.Base.BASIN
    )

    queued = mock_queue.put.call_args.args[0]
    assert queued.items[0]["_JobID"] == 42


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data', side_effect=_http_error(401))
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_skips_unauthorized(mock_token, mock_request,
                                               mock_queue):
    """A 401 leaves the job PENDING and excludes it from this run."""

    config = hidrocli.jobs.runner.JobConfig.Series.RAIN
    job    = MagicMock()
    job.ID = 42
    job.Status = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(job, config)

    assert job.Status == hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    mock_queue.put.assert_not_called()


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data',
       side_effect=_http_error(417, SQL_GRAMMAR_BODY))
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_marks_invalid_on_api_error(mock_token,
                                                       mock_request,
                                                       mock_queue):
    """A 417 with a SQLGrammarException body marks the job INVALID."""

    config = hidrocli.jobs.runner.JobConfig.Series.GRANULOMETRY
    job    = MagicMock()
    job.ID        = 42
    job.Status    = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.Retries   = 0
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(job, config)

    assert job.Status  == hidrocli.jobs.runner.JobConfig.Status.INVALID.value
    assert job.Retries == 0
    mock_queue.put.assert_called_once()
    queued = mock_queue.put.call_args.args[0]
    assert queued.job.Status == hidrocli.jobs.runner.JobConfig.Status.INVALID.value
    assert queued.items == []


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data',
       side_effect=hidrocli.jobs.runner.RequestException("Connection aborted."))
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_skips_on_request_error(mock_token, mock_request,
                                                   mock_queue):
    """A network error leaves the job PENDING and excludes it from this run."""

    config = hidrocli.jobs.runner.JobConfig.Series.GRANULOMETRY
    job    = MagicMock()
    job.ID        = 42
    job.Status    = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.Retries   = 0
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(job, config)

    assert job.Status  == hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    assert job.Retries == 0
    mock_queue.put.assert_not_called()


@patch('hidrocli.jobs.runner._throttle')
@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data',
       side_effect=ReadTimeout("read timed out"))
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_skips_and_throttles_on_timeout(
        mock_token, mock_request, mock_queue, mock_throttle):
    """A timeout leaves the job PENDING, keeps retries, and throttles the pool."""

    config = hidrocli.jobs.runner.JobConfig.Telemetry.TELEMETRY
    job    = MagicMock()
    job.ID        = 42
    job.Status    = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.Retries   = 0
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(job, config)

    assert job.Status  == hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    assert job.Retries == 0
    mock_queue.put.assert_not_called()
    mock_throttle.assert_called_once()


@patch('hidrocli.jobs.runner._throttle')
@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data',
       side_effect=ReadTimeout("read timed out"))
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_counts_read_json_timeout(
        mock_token, mock_request, mock_queue, mock_throttle, monkeypatch):
    """A timed-out cache fallback increments the read-json error counter."""

    _set_config(monkeypatch, READ_JSON=True)
    hidrocli.jobs.runner._reset_request_errors()
    job = MagicMock()
    job.ID      = 42
    job.Status  = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.Retries = 0
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(
        job, hidrocli.jobs.runner.JobConfig.Telemetry.TELEMETRY
    )

    assert hidrocli.jobs.runner._request_error_count() == 1
    assert job.Status == hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    assert job.Retries == 0


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data', return_value=(False, []))
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_counts_read_json_failed_request(
        mock_token, mock_request, mock_queue, monkeypatch):
    """A failed cache-miss API request increments the read-json error counter."""

    _set_config(monkeypatch, READ_JSON=True)
    hidrocli.jobs.runner._reset_request_errors()
    job = MagicMock()
    job.ID      = 42
    job.Status  = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.Retries = 0
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(
        job, hidrocli.jobs.runner.JobConfig.Telemetry.TELEMETRY
    )

    assert hidrocli.jobs.runner._request_error_count() == 1


@patch('hidrocli.jobs.runner._throttle')
@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data', side_effect=_http_error(500))
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_counts_read_json_http_error(
        mock_token, mock_request, mock_queue, mock_throttle, monkeypatch):
    """Any HTTP failure from a cache fallback counts in read-json mode."""

    _set_config(monkeypatch, READ_JSON=True)
    hidrocli.jobs.runner._reset_request_errors()
    job = MagicMock()
    job.ID      = 42
    job.Status  = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.Retries = 0
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(
        job, hidrocli.jobs.runner.JobConfig.Telemetry.TELEMETRY
    )

    assert hidrocli.jobs.runner._request_error_count() == 1


@patch('hidrocli.jobs.runner._throttle')
@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data', side_effect=_http_error(504))
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_skips_on_server_error(mock_token, mock_request,
                                                  mock_queue, mock_throttle):
    """A 5xx server error leaves the job PENDING and throttles the pool."""

    config = hidrocli.jobs.runner.JobConfig.Series.GRANULOMETRY
    job    = MagicMock()
    job.ID        = 42
    job.Status    = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.Retries   = 0
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(job, config)

    assert job.Status  == hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    assert job.Retries == 0
    mock_queue.put.assert_not_called()
    mock_throttle.assert_called_once()


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data', side_effect=_http_error(400))
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_marks_failed_on_unhandled_http(mock_token,
                                                           mock_request,
                                                           mock_queue):
    """A non-401/5xx/417-SQLGrammar HTTP error marks the job FAILED."""

    config = hidrocli.jobs.runner.JobConfig.Series.GRANULOMETRY
    job    = MagicMock()
    job.ID        = 42
    job.Status    = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.Retries   = 0
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(job, config)

    assert job.Status  == hidrocli.jobs.runner.JobConfig.Status.FAILED.value
    assert job.Retries == 1
    mock_queue.put.assert_called_once()


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data', side_effect=_http_error(417))
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_marks_failed_on_417_without_sql(mock_token,
                                                            mock_request,
                                                            mock_queue):
    """A 417 without the SQLGrammarException body is unhandled -> FAILED."""

    config = hidrocli.jobs.runner.JobConfig.Series.GRANULOMETRY
    job    = MagicMock()
    job.ID        = 42
    job.Status    = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.Retries   = 0
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(job, config)

    assert job.Status  == hidrocli.jobs.runner.JobConfig.Status.FAILED.value
    assert job.Retries == 1
    mock_queue.put.assert_called_once()


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data', return_value=(False, []))
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_marks_failed_and_increments_retries(
        mock_token, mock_request, mock_queue):
    """A failed request marks a series job FAILED and bumps its retries."""

    config = hidrocli.jobs.runner.JobConfig.Series.GRANULOMETRY
    job    = MagicMock()
    job.ID        = 42
    job.Status    = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.Retries   = 0
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(job, config)

    assert job.Status  == hidrocli.jobs.runner.JobConfig.Status.FAILED.value
    assert job.Retries == 1
    mock_queue.put.assert_called_once()


def test_is_sql_grammar():
    """Only the exact 417 SQLGrammarException body is recognized."""

    assert hidrocli.jobs.runner._is_sql_grammar(
        _http_error(417, SQL_GRAMMAR_BODY).response
    )
    assert not hidrocli.jobs.runner._is_sql_grammar(None)
    assert not hidrocli.jobs.runner._is_sql_grammar(_http_error(400).response)
    assert not hidrocli.jobs.runner._is_sql_grammar(
        _http_error(417, {"code": 417, "message": "some other error"}).response
    )


def test_filter_cross_section_returns_empty_without_ana_id():
    items = [{"codigoestacao": 1}]

    filtered = hidrocli.jobs.runner.filter_repeated_series_items(
        hidrocli.jobs.runner.JobConfig.Series.CROSS_SECTION, items
    )

    assert filtered == []


def test_validate_cross_section_allows_missing_ana_id():
    item = {
        "Cota":               50.0,
        "Data_Hora_Medicao":  datetime(2024, 1, 1),
        "Data_Ultima_Alteracao": None,
        "Distancia":          5.0,
        "Distancia_pipf":     10.0,
        "Eixo_X_Dist_Maxima": 10.0,
        "Eixo_X_Dist_Minima": 0.0,
        "Eixo_Y_Cota_Maxima": 100.0,
        "Eixo_Y_Cota_Minima": 0.0,
        "Elm_Geom_Passo_Cota": 10.0,
        "Nivel_Consistencia": 1,
        "Num_Levantamento":   1,
        "Num_Verticais":      1,
        "Observacoes":        "",
        "Tipo_Secao":         1,
        "codigoestacao":      1,
        "verticais":          [],
    }
    job = MagicMock()
    job.ID = 1
    job.Status = hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    job.Retries = 0

    normalized = hidrocli.jobs.runner.normalize_items(
        "PerfilTransversal", [dict(item)]
    )
    valid = hidrocli.jobs.runner.validate_series_items(
        job, hidrocli.jobs.runner.JobConfig.Series.CROSS_SECTION, normalized
    )

    assert valid == normalized
    assert job.Status == hidrocli.jobs.runner.JobConfig.Status.PENDING.value
    assert job.Retries == 0


@patch('hidrocli.jobs.runner.reset_series_job_dates', return_value=3)
@patch('hidrocli.jobs.runner.get_period')
def test_update_series_job_uses_bulk_reset(mock_period, mock_reset,
                                           monkeypatch):
    mock_period.return_value.scalars.return_value.all.return_value = [1, 2, 3]
    _set_config(monkeypatch, BATCH_SIZE=500)

    hidrocli.jobs.runner.update_series_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    mock_reset.assert_called_once()
    args = mock_reset.call_args.args
    assert args[0] == hidrocli.jobs.runner.JobConfig.Series.RAIN
    assert args[1] == [1, 2, 3]
    assert args[3] == 500


@patch('hidrocli.jobs.runner.reset_series_job_dates', return_value=0)
@patch('hidrocli.jobs.runner.get_period')
def test_update_series_job_scopes_selected_stations(mock_period, mock_reset,
                                                    monkeypatch):
    mock_period.return_value.scalars.return_value.all.return_value = [1, 2, 3]
    _set_config(monkeypatch, STATIONS=[2, 4])

    hidrocli.jobs.runner.update_series_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    assert mock_reset.call_args.args[1] == [2]


@patch('hidrocli.jobs.runner.update_series_job')
@patch('hidrocli.jobs.runner.count_job', return_value=0)
@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.create_series_jobs')
@patch('hidrocli.jobs.runner.get_station_ids')
@patch('hidrocli.jobs.runner.get_period')
@pytest.mark.parametrize("stations", [
    [1, 2, 3],
    [],
])
def test_check_series_job_creates_only_missing_stations(
        mock_period, mock_station_ids, mock_create, mock_trigger,
        mock_count, mock_update, monkeypatch, stations):
    mock_period.return_value.all.return_value = [
        (1, "start", "end"),
        (2, "start", "end"),
        (3, "start", "end"),
    ]
    mock_station_ids.return_value = {1, 3}
    _set_config(monkeypatch, STATIONS=stations)

    hidrocli.jobs.runner.check_series_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    mock_create.assert_called_once()
    assert [row[0] for row in mock_create.call_args.args[0]] == [2]
    mock_station_ids.assert_any_call(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, stations
    )
    mock_update.assert_called_once()
    mock_trigger.assert_not_called()


@patch('hidrocli.jobs.runner.update_series_job')
@patch('hidrocli.jobs.runner.count_job', return_value=0)
@patch('hidrocli.jobs.runner.create_series_jobs')
@patch('hidrocli.jobs.runner.get_station_ids', return_value={1})
@patch('hidrocli.jobs.runner.get_period')
def test_check_series_job_warns_for_unknown_station(
        mock_period, mock_station_ids, mock_create, mock_count,
        mock_update, monkeypatch, caplog):
    mock_period.return_value.all.return_value = [(1, "start", "end")]
    _set_config(monkeypatch, STATIONS=[1, 99])

    hidrocli.jobs.runner.check_series_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    mock_create.assert_not_called()
    assert "99" in caplog.text


@patch('hidrocli.jobs.runner.create_job_filters', return_value=[])
@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.count_job', side_effect=[2, 0])
def test_trigger_jobs_retries_until_none(mock_count, mock_trigger,
                                         mock_filters):
    hidrocli.jobs.runner.trigger_jobs(
        hidrocli.jobs.runner.JobConfig.Series.RAIN,
        hidrocli.jobs.runner.SERIES_RETRY_DEPTH,
    )

    assert mock_count.call_count == 2
    mock_trigger.assert_called_once_with(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, [], 2
    )
    assert mock_filters.call_args.args[1] == [
        hidrocli.jobs.runner.JobConfig.Status.FAILED.value,
        hidrocli.jobs.runner.JobConfig.Status.PENDING.value,
    ]
    assert mock_filters.call_args.kwargs["max_retries"] is True


@patch('hidrocli.jobs.runner.create_job_filters', return_value=[])
@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.count_job', return_value=1)
def test_trigger_jobs_stops_at_retry_depth(mock_count, mock_trigger,
                                           mock_filters, caplog):
    """Persistent pending jobs stop after the configured same-run retries."""

    with caplog.at_level(logging.WARNING):
        hidrocli.jobs.runner.trigger_jobs(
            hidrocli.jobs.runner.JobConfig.Series.RAIN,
            hidrocli.jobs.runner.SERIES_RETRY_DEPTH,
        )

    assert mock_trigger.call_count == 1 + hidrocli.jobs.runner.SERIES_RETRY_DEPTH
    assert "remain pending/failed after" in caplog.text


def test_process_period_creates_yearly_windows():
    jobs = hidrocli.jobs.runner.process_period(
        1,
        datetime(2020, 6, 1),
        datetime(2022, 1, 1),
        hidrocli.jobs.runner.JobConfig.Series.RAIN,
    )

    assert [(job.FromDate, job.ToDate) for job in jobs] == [
        (datetime(2020, 6, 1), datetime(2021, 6, 1)),
        (datetime(2021, 6, 1), datetime(2022, 1, 1)),
    ]


def _series_job(job_id, station, start, end, status=5, retries=0):
    job = hidrocli.jobs.runner.SeriesJobs(
        HidroTable=hidrocli.jobs.runner.JobConfig.Series.RAIN,
        StationID=station,
        FromDate=start,
        ToDate=end,
        Status=status,
        Retries=retries,
    )
    job.ID = job_id
    return job


def test_reconcile_jobs_keeps_updates_and_inserts():
    exact   = _series_job(1, 10, datetime(2020, 1, 1), datetime(2021, 1, 1))
    overlap = _series_job(2, 10, datetime(2020, 6, 1), datetime(2021, 6, 1))
    jobs    = [exact, overlap]
    desired = [
        _series_job(None, 10, datetime(2020, 1, 1), datetime(2021, 1, 1), status=1),
        _series_job(None, 10, datetime(2021, 1, 1), datetime(2022, 1, 1), status=1),
        _series_job(None, 10, datetime(2022, 1, 1), datetime(2023, 1, 1), status=1),
    ]

    updates, new_jobs = hidrocli.jobs.runner._reconcile_jobs(jobs, desired)

    assert updates == [{
        "ID":       overlap.ID,
        "FromDate": desired[1].FromDate,
        "ToDate":   desired[1].ToDate,
        "Status":   desired[1].Status,
        "Retries":  0,
    }]
    assert new_jobs == [desired[2]]
    assert jobs == []


@patch('hidrocli.jobs.runner.insert_jobs_bulk')
@patch('hidrocli.jobs.runner.update_job_mappings')
@patch('hidrocli.jobs.runner.iter_jobs')
def test_update_series_job_windows_keeps_exact_matches(
        mock_iter, mock_update, mock_insert, monkeypatch):
    start, end = datetime(2020, 1, 1), datetime(2021, 1, 1)
    mock_iter.return_value = [_series_job(1, 10, start, end)]
    _set_config(monkeypatch, BATCH_SIZE=100)

    hidrocli.jobs.runner.update_series_job_windows(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, [(10, start, end)]
    )

    mock_update.assert_not_called()
    mock_insert.assert_not_called()


@patch('hidrocli.jobs.runner.insert_jobs_bulk')
@patch('hidrocli.jobs.runner.update_job_mappings')
@patch('hidrocli.jobs.runner.iter_jobs')
def test_update_series_job_windows_updates_overlapping_job(
        mock_iter, mock_update, mock_insert, monkeypatch):
    job = _series_job(
        7, 10, datetime(2020, 1, 1), datetime(2021, 1, 1),
        status=5, retries=3,
    )
    mock_iter.return_value = [job]
    _set_config(monkeypatch, BATCH_SIZE=100)
    start, end = datetime(2020, 6, 1), datetime(2021, 6, 1)

    hidrocli.jobs.runner.update_series_job_windows(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, [(10, start, end)]
    )

    mock_update.assert_called_once()
    mapping = mock_update.call_args.args[1][0]
    assert mapping == {
        "ID":       job.ID,
        "FromDate": start,
        "ToDate":   end,
        "Status":   hidrocli.jobs.runner.JobConfig.Status.PENDING.value,
        "Retries":  0,
    }
    mock_insert.assert_not_called()


@patch('hidrocli.jobs.runner.insert_jobs_bulk')
@patch('hidrocli.jobs.runner.update_job_mappings')
@patch('hidrocli.jobs.runner.iter_jobs', return_value=[])
def test_update_series_job_windows_inserts_missing_year(
        mock_iter, mock_update, mock_insert, monkeypatch):
    _set_config(monkeypatch, BATCH_SIZE=100)
    start, end = datetime(2020, 1, 1), datetime(2021, 1, 1)

    hidrocli.jobs.runner.update_series_job_windows(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, [(10, start, end)]
    )

    mock_update.assert_not_called()
    mock_insert.assert_called_once()
    inserted = mock_insert.call_args.args[0][0]
    assert inserted.StationID == 10
    assert inserted.FromDate == start
    assert inserted.ToDate == end
    assert inserted.Status == hidrocli.jobs.runner.JobConfig.Status.PENDING.value


@patch('hidrocli.jobs.runner.trigger_jobs')
@patch('hidrocli.jobs.runner.update_series_job')
@patch('hidrocli.jobs.runner.update_series_job_windows')
@patch('hidrocli.jobs.runner.create_series_jobs')
@patch('hidrocli.jobs.runner.get_station_ids', return_value={2})
@patch('hidrocli.jobs.runner.get_period')
def test_check_series_job_applies_date_overrides(
        mock_period, mock_station_ids, mock_create, mock_update_windows,
        mock_update, mock_trigger, monkeypatch):
    mock_period.return_value.all.return_value = [
        (1, datetime(2000, 1, 1), datetime(2010, 1, 1)),
        (2, datetime(2001, 1, 1), datetime(2011, 1, 1)),
    ]
    _set_config(
        monkeypatch,
        STATIONS=[], INITIAL_DATE=datetime(2005, 1, 1),
        FINAL_DATE=datetime(2008, 1, 1),
    )

    hidrocli.jobs.runner.check_series_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    mock_create.assert_called_once()
    created = mock_create.call_args.args[0]
    assert created == [(1, datetime(2005, 1, 1), datetime(2008, 1, 1))]
    mock_update_windows.assert_called_once()
    assert mock_update_windows.call_args.args == (
        hidrocli.jobs.runner.JobConfig.Series.RAIN,
        [(2, datetime(2005, 1, 1), datetime(2008, 1, 1))],
    )
    assert mock_update_windows.call_args.kwargs["stats"] == {
        "created": 0, "updated": 0,
    }
    mock_update.assert_not_called()
    mock_trigger.assert_called_once()


@patch('hidrocli.jobs.runner.trigger_jobs')
@patch('hidrocli.jobs.runner.update_series_job')
@patch('hidrocli.jobs.runner.update_series_job_windows')
@patch('hidrocli.jobs.runner.create_series_jobs')
@patch('hidrocli.jobs.runner.get_station_ids', return_value=set())
@patch('hidrocli.jobs.runner.get_period')
def test_check_series_job_keeps_stale_reset_without_final_date(
        mock_period, mock_station_ids, mock_create, mock_update_windows,
        mock_update, mock_trigger, monkeypatch):
    mock_period.return_value.all.return_value = [
        (1, datetime(2000, 1, 1), datetime(2010, 1, 1)),
    ]
    _set_config(
        monkeypatch,
        STATIONS=[], INITIAL_DATE=datetime(2005, 1, 1), FINAL_DATE=None,
    )

    hidrocli.jobs.runner.check_series_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    mock_update.assert_called_once_with(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )


@patch('hidrocli.jobs.runner.create_job_filters', return_value=[])
@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.count_job', return_value=0)
def test_trigger_jobs_passes_date_bounds(
        mock_count, mock_trigger, mock_filters, monkeypatch):
    initial = datetime(2020, 1, 1)
    final   = datetime(2021, 1, 1)
    _set_config(monkeypatch, INITIAL_DATE=initial, FINAL_DATE=final)

    hidrocli.jobs.runner.trigger_jobs(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    assert mock_filters.call_args.kwargs["initial_date"] == initial
    assert mock_filters.call_args.kwargs["final_date"] == final

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

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import hidrocli.jobs.runner

from hidrocli.config import setup_logger
from hidrocli.database import DatabaseType, _setup_db
from hidrocli.jobs.runner import (
    JobConfig, _telemetry_station_windows, create_telemetry_jobs,
    telemetry_range, telemetry_windows,
)
from hidrocli.models.client import ClientBase, TelemetryJobs

setup_logger()


def _set_config(monkeypatch, **kwargs):
    """Replace the runner's frozen CONFIG with the given fields updated."""

    monkeypatch.setattr(
        hidrocli.jobs.runner, "CONFIG",
        hidrocli.jobs.runner.CONFIG._replace(**kwargs),
    )


def plan(stations, today=None):
    """Build telemetry windows using the runner's station helper."""
    yesterday = (today or date.today()) - timedelta(days=1)
    return [
        window
        for row in stations
        for window in _telemetry_station_windows(row, yesterday)
    ]


@pytest.fixture
def client_db(tmp_path):
    connection = _setup_db(str(tmp_path / "client.db"), DatabaseType.CLIENT)
    with patch("hidrocli.database.client.CLIENT_DB", connection):
        yield connection
        ClientBase.metadata.drop_all(connection.engine)
        connection.close()


def jobs(connection):
    session = connection.get_session()
    try:
        return session.query(TelemetryJobs).order_by(TelemetryJobs.Date).all()
    finally:
        session.close()


def insert_telemetry_job(connection, station, job_date, range_="DIAS_30",
                         status=JobConfig.Status.COMPLETED.value):
    session = connection.get_session()
    try:
        session.add(TelemetryJobs(
            HidroTable="Telemetria",
            StationID=station,
            Date=job_date,
            Range=range_,
            Status=status,
            Retries=0,
        ))
        session.commit()
    finally:
        session.close()


@pytest.mark.parametrize("remaining, expected", [
    (timedelta(days=30),    "DIAS_30"),
    (timedelta(days=29),    "DIAS_30"),
    (timedelta(days=21),    "DIAS_21"),
    (timedelta(days=20),    "DIAS_21"),
    (timedelta(days=14),    "DIAS_14"),
    (timedelta(days=7),     "DIAS_7"),
    (timedelta(days=2),     "DIAS_2"),
    (timedelta(days=1),     "HORA_24"),
    (timedelta(hours=18),   "HORA_18"),
    (timedelta(minutes=30), "MINUTO_30"),
    (timedelta(minutes=5),  "MINUTO_5"),
])
def test_telemetry_range(remaining, expected):
    assert telemetry_range(remaining) == expected


def test_telemetry_windows_inclusive_days():
    assert telemetry_windows(date(2024, 1, 1), date(2024, 1, 30)) == [
        (date(2024, 1, 1), "DIAS_30"),
    ]
    assert telemetry_windows(date(2024, 1, 1), date(2024, 1, 31)) == [
        (date(2024, 1, 1), "DIAS_30"),
        (date(2024, 1, 31), "HORA_24"),
    ]
    assert telemetry_windows(date(2024, 1, 1), date(2024, 1, 15)) == [
        (date(2024, 1, 1), "DIAS_21"),
    ]
    assert telemetry_windows(date(2024, 1, 1), date(2024, 1, 14)) == [
        (date(2024, 1, 1), "DIAS_14"),
    ]
    assert telemetry_windows(date(2024, 1, 1), date(2024, 1, 2)) == [
        (date(2024, 1, 1), "DIAS_2"),
    ]
    assert telemetry_windows(date(2024, 1, 1), date(2024, 1, 1)) == [
        (date(2024, 1, 1), "HORA_24"),
    ]


def test_telemetry_windows_timed_fim_uses_minutes():
    assert telemetry_windows(
        datetime(2024, 1, 1, 0, 0), datetime(2024, 1, 1, 0, 30)
    ) == [(date(2024, 1, 1), "MINUTO_30")]


def test_telemetry_windows_active_always_dias_30():
    assert telemetry_windows(
        date(2024, 1, 1), date(2024, 1, 31), active=True
    ) == [
        (date(2024, 1, 1), "DIAS_30"),
        (date(2024, 1, 31), "DIAS_30"),
    ]


def test_plan_skips_invalid_period():
    rows = [
        (1, datetime(2024, 1, 1), datetime(2024, 1, 31)),
        (2, datetime(2024, 2, 1), datetime(2024, 1, 1)),
    ]

    assert plan(rows, today=date(2024, 3, 1)) == [
        (1, date(2024, 1, 1), "DIAS_30"),
        (1, date(2024, 1, 31), "HORA_24"),
    ]


def test_plan_clamps_to_requested_dates(monkeypatch):
    _set_config(
        monkeypatch,
        INITIAL_DATE=datetime(2024, 1, 10),
        FINAL_DATE=datetime(2024, 1, 20),
    )
    rows = [(1, datetime(2024, 1, 1), datetime(2024, 2, 1))]

    assert plan(rows) == [
        (1, date(2024, 1, 10), "DIAS_14"),
    ]


def test_plan_final_date_overrides_active_station(monkeypatch):
    _set_config(
        monkeypatch,
        INITIAL_DATE=None,
        FINAL_DATE=datetime(2024, 1, 31),
    )
    rows = [(1, datetime(2024, 1, 1), None)]

    assert plan(rows) == [
        (1, date(2024, 1, 1), "DIAS_30"),
        (1, date(2024, 1, 31), "HORA_24"),
    ]


def test_create_telemetry_jobs_inserts_windows(client_db, monkeypatch):
    _set_config(
        monkeypatch, INITIAL_DATE=None, FINAL_DATE=None,
        BATCH_SIZE=1000,
    )
    rows = [(1, datetime(2024, 1, 1), datetime(2024, 1, 31))]

    create_telemetry_jobs(rows, JobConfig.Telemetry.TELEMETRY)

    assert [
        (job.StationID, job.Date.date(), job.Range, job.Status)
        for job in jobs(client_db)
    ] == [
        (1, date(2024, 1, 1), "DIAS_30", JobConfig.Status.PENDING.value),
        (1, date(2024, 1, 31), "HORA_24", JobConfig.Status.PENDING.value),
    ]


def test_create_telemetry_jobs_is_idempotent(client_db, monkeypatch):
    _set_config(monkeypatch, INITIAL_DATE=None, FINAL_DATE=None)
    rows = [(1, datetime(2024, 1, 1), datetime(2024, 1, 31))]

    create_telemetry_jobs(rows, JobConfig.Telemetry.TELEMETRY)
    create_telemetry_jobs(rows, JobConfig.Telemetry.TELEMETRY)

    assert len(jobs(client_db)) == 2


def test_create_telemetry_jobs_narrows_tail_and_resets_status(
        client_db, monkeypatch):
    _set_config(monkeypatch, INITIAL_DATE=None, FINAL_DATE=None)
    create_telemetry_jobs(
        [(1, datetime(2024, 1, 1), datetime(2024, 1, 15))],
        JobConfig.Telemetry.TELEMETRY,
    )

    session = client_db.get_session()
    job = session.query(TelemetryJobs).one()
    job.Status = JobConfig.Status.COMPLETED.value
    job.Retries = 2
    session.commit()
    session.close()

    create_telemetry_jobs(
        [(1, datetime(2024, 1, 1), datetime(2024, 1, 14))],
        JobConfig.Telemetry.TELEMETRY,
    )

    saved = jobs(client_db)
    assert len(saved) == 1
    assert saved[0].Range == "DIAS_14"
    assert saved[0].Status == JobConfig.Status.PENDING.value
    assert saved[0].Retries == 0


def test_create_telemetry_jobs_appends_active_windows(client_db, monkeypatch):
    _set_config(monkeypatch, INITIAL_DATE=None, FINAL_DATE=None)
    create_telemetry_jobs(
        [(1, datetime(2024, 1, 1), None)],
        JobConfig.Telemetry.TELEMETRY,
        today=date(2024, 1, 10),
    )
    assert len(jobs(client_db)) == 1

    create_telemetry_jobs(
        [(1, datetime(2024, 1, 1), None)],
        JobConfig.Telemetry.TELEMETRY,
        today=date(2024, 2, 10),
    )

    assert [(job.Date.date(), job.Range) for job in jobs(client_db)] == [
        (date(2024, 1, 1), "DIAS_30"),
        (date(2024, 1, 31), "DIAS_30"),
    ]


def test_create_telemetry_jobs_inserts_in_batches(client_db, monkeypatch):
    _set_config(
        monkeypatch, INITIAL_DATE=None, FINAL_DATE=None, BATCH_SIZE=2,
    )

    calls = []
    original = hidrocli.jobs.runner.insert_jobs_bulk

    def spy(new_jobs):
        calls.append(len(new_jobs))
        return original(new_jobs)

    monkeypatch.setattr(hidrocli.jobs.runner, "insert_jobs_bulk", spy)

    rows = [
        (station, datetime(2024, 1, 1), datetime(2024, 1, 31))
        for station in range(1, 6)
    ]
    create_telemetry_jobs(rows, JobConfig.Telemetry.TELEMETRY)

    assert len(jobs(client_db)) == 10
    assert calls == [2, 2, 2, 2, 2]


def test_create_telemetry_jobs_never_splits_a_station(client_db, monkeypatch):
    _set_config(
        monkeypatch, INITIAL_DATE=None, FINAL_DATE=None, BATCH_SIZE=1,
    )

    create_telemetry_jobs(
        [(1, datetime(2024, 1, 1), datetime(2024, 3, 31))],
        JobConfig.Telemetry.TELEMETRY,
    )

    saved = jobs(client_db)
    assert len(saved) == 4
    assert len({(job.StationID, job.Date) for job in saved}) == 4


def test_create_telemetry_jobs_tracks_station_progress(
        client_db, monkeypatch):
    _set_config(
        monkeypatch, INITIAL_DATE=None, FINAL_DATE=None, BATCH_SIZE=1000,
    )
    bar = MagicMock()
    descs = []
    monkeypatch.setattr(
        hidrocli.jobs.runner, "_make_progress_bar",
        lambda total, desc: descs.append(desc) or bar,
    )
    monkeypatch.setattr(
        hidrocli.jobs.runner, "_bar_stats", lambda *args, **kwargs: "",
    )

    rows = [
        (station, datetime(2024, 1, 1), datetime(2024, 1, 2))
        for station in range(1, 4)
    ]
    create_telemetry_jobs(rows, JobConfig.Telemetry.TELEMETRY)

    assert descs == ["Check"]
    assert bar.update.call_count == 3
    bar.update.assert_called_with(1)
    bar.close.assert_called_once()


def test_create_telemetry_jobs_reports_created_and_updated(
        client_db, monkeypatch):
    _set_config(
        monkeypatch, INITIAL_DATE=None, FINAL_DATE=None, BATCH_SIZE=1000,
    )
    insert_telemetry_job(
        client_db, 1, datetime(2024, 1, 1), range_="DIAS_14",
    )

    bar = MagicMock()
    stats_calls = []
    descs = []
    monkeypatch.setattr(
        hidrocli.jobs.runner, "_make_progress_bar",
        lambda total, desc: descs.append(desc) or bar,
    )
    monkeypatch.setattr(
        hidrocli.jobs.runner, "_bar_stats",
        lambda *args, **kwargs: stats_calls.append(kwargs) or "",
    )

    rows = [
        (station, datetime(2024, 1, 1), datetime(2024, 1, 30))
        for station in (1, 2)
    ]
    create_telemetry_jobs(rows, JobConfig.Telemetry.TELEMETRY)

    assert descs == ["Check"]
    assert stats_calls[-1]["created"] == 1
    assert stats_calls[-1]["updated"] == 1


@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.count_job', return_value=1)
@patch('hidrocli.jobs.runner.get_telemetry_stations')
def test_check_telemetry_job_uses_station_and_date_filters(
        mock_stations, mock_count, mock_trigger, client_db, monkeypatch):
    mock_stations.return_value = [
        (1, datetime(2024, 1, 1), datetime(2024, 1, 2)),
    ]
    _set_config(
        monkeypatch, STATIONS=(1,),
        INITIAL_DATE=datetime(2024, 1, 1),
        FINAL_DATE=datetime(2024, 1, 2),
        BATCH_SIZE=1000,
    )

    hidrocli.jobs.runner.check_telemetry_job(
        JobConfig.Telemetry.TELEMETRY
    )

    mock_stations.assert_called_once_with((1,))
    mock_trigger.assert_called_once()
    assert len(jobs(client_db)) == 1


@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.count_job', return_value=0)
@patch('hidrocli.jobs.runner.get_telemetry_stations')
@patch('hidrocli.jobs.runner.create_telemetry_jobs')
def test_check_telemetry_job_skips_creation_when_tail_is_current(
        mock_create, mock_stations, mock_count, mock_trigger,
        client_db, monkeypatch):
    latest = datetime.combine(
        date.today() - timedelta(days=1), datetime.min.time()
    )
    insert_telemetry_job(client_db, 1, latest)
    mock_stations.return_value = [(1, datetime(2024, 1, 1), None)]
    _set_config(
        monkeypatch, STATIONS=(), INITIAL_DATE=None, FINAL_DATE=None,
    )

    hidrocli.jobs.runner.check_telemetry_job(
        JobConfig.Telemetry.TELEMETRY
    )

    mock_create.assert_not_called()


@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.count_job', return_value=0)
@patch('hidrocli.jobs.runner.get_telemetry_stations')
@patch('hidrocli.jobs.runner.create_telemetry_jobs')
def test_check_telemetry_job_creates_only_missing_stations(
        mock_create, mock_stations, mock_count, mock_trigger,
        client_db, monkeypatch):
    insert_telemetry_job(client_db, 1, datetime(2024, 1, 1))
    mock_stations.return_value = [
        (1, datetime(2024, 1, 1), datetime(2024, 1, 31)),
        (2, datetime(2024, 1, 1), datetime(2024, 1, 31)),
    ]
    _set_config(
        monkeypatch, STATIONS=(), INITIAL_DATE=None, FINAL_DATE=None,
    )

    hidrocli.jobs.runner.check_telemetry_job(
        JobConfig.Telemetry.TELEMETRY
    )

    mock_create.assert_called_once()
    rows = mock_create.call_args[0][0]
    assert [row[0] for row in rows] == [2]


@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.count_job', return_value=0)
@patch('hidrocli.jobs.runner.get_telemetry_stations')
@patch('hidrocli.jobs.runner.create_telemetry_jobs')
def test_check_telemetry_job_appends_due_active_tail(
        mock_create, mock_stations, mock_count, mock_trigger,
        client_db, monkeypatch):
    latest = datetime.combine(
        date.today() - timedelta(days=60), datetime.min.time()
    )
    insert_telemetry_job(client_db, 1, latest)
    mock_stations.return_value = [(1, datetime(2024, 1, 1), None)]
    _set_config(
        monkeypatch, STATIONS=(), INITIAL_DATE=None, FINAL_DATE=None,
    )

    hidrocli.jobs.runner.check_telemetry_job(
        JobConfig.Telemetry.TELEMETRY
    )

    mock_create.assert_called_once()
    assert mock_create.call_args[0][0] == [(1, latest, None)]


@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.count_job', return_value=0)
@patch('hidrocli.jobs.runner.get_telemetry_stations')
@patch('hidrocli.jobs.runner.create_telemetry_jobs')
def test_check_telemetry_job_merges_missing_and_tail_into_one_call(
        mock_create, mock_stations, mock_count, mock_trigger,
        client_db, monkeypatch):
    latest = datetime.combine(
        date.today() - timedelta(days=60), datetime.min.time()
    )
    insert_telemetry_job(client_db, 1, latest)
    mock_stations.return_value = [
        (1, datetime(2024, 1, 1), None),
        (2, datetime(2024, 1, 1), datetime(2024, 1, 31)),
    ]
    _set_config(
        monkeypatch, STATIONS=(), INITIAL_DATE=None, FINAL_DATE=None,
    )

    hidrocli.jobs.runner.check_telemetry_job(
        JobConfig.Telemetry.TELEMETRY
    )

    mock_create.assert_called_once()
    rows = mock_create.call_args[0][0]
    assert [row[0] for row in rows] == [2, 1]
    assert rows[1] == (1, latest, None)


@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.count_job', return_value=0)
@patch('hidrocli.jobs.runner.get_telemetry_stations')
@patch('hidrocli.jobs.runner.create_telemetry_jobs')
def test_check_telemetry_job_reconciles_existing_for_date_window(
        mock_create, mock_stations, mock_count, mock_trigger,
        client_db, monkeypatch):
    insert_telemetry_job(client_db, 1, datetime(2024, 1, 1))
    rows = [(1, datetime(2024, 1, 1), datetime(2024, 1, 31))]
    mock_stations.return_value = rows
    _set_config(
        monkeypatch, STATIONS=(),
        INITIAL_DATE=datetime(2024, 1, 1),
        FINAL_DATE=datetime(2024, 1, 31),
    )

    hidrocli.jobs.runner.check_telemetry_job(
        JobConfig.Telemetry.TELEMETRY
    )

    mock_create.assert_called_once()
    assert mock_create.call_args[0][0] == rows


def test_mark_failed_increments_telemetry_retries():
    job = TelemetryJobs(
        HidroTable="Telemetria", StationID=1,
        Date=datetime(2024, 1, 1), Range="DIAS_30",
        Status=1, Retries=0,
    )

    hidrocli.jobs.runner._mark_failed(
        job, JobConfig.Telemetry.TELEMETRY
    )

    assert job.Status == JobConfig.Status.FAILED.value
    assert job.Retries == 1


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data')
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_telemetry(mock_token, mock_request, mock_queue,
                                      monkeypatch):
    _set_config(monkeypatch, READ_JSON=False, SAVE_JSON=False)
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "Telemetria.json").read_text()
    )
    mock_request.return_value = (True, [dict(fixture[0])])
    job = TelemetryJobs(
        HidroTable="Telemetria",
        Status=JobConfig.Status.PENDING.value,
        StationID=15324500,
        Date=datetime(2024, 5, 28),
        Range="DIAS_30",
        Retries=0,
    )
    job.ID = 1

    hidrocli.jobs.runner.handle_job_request(
        job, JobConfig.Telemetry.TELEMETRY
    )

    assert job.Status == JobConfig.Status.COMPLETED.value
    queued = mock_queue.put.call_args[0][0]
    assert queued.items[0]["EstacaoCodigo"] == 15324500
    assert queued.items[0]["Cota_Sensor"] == 1114.0
    assert isinstance(queued.items[0]["Data_Hora_Medicao"], datetime)
    assert queued.items[0]["_JobID"] == 1


@patch('hidrocli.jobs.runner.check_telemetry_job')
@patch('hidrocli.jobs.runner.check_series_job')
@patch('hidrocli.jobs.runner.check_base_job')
def test_run_runs_telemetry_after_series(mock_base, mock_series,
                                         mock_telemetry, monkeypatch):
    _set_config(
        monkeypatch, SKIP_SERIES_JOBS=False, SKIP_FOR=(), RUN_FOR=(),
    )

    hidrocli.jobs.runner.run(hidrocli.jobs.runner.CONFIG)

    assert mock_base.call_count == len(JobConfig.Base)
    assert mock_series.call_count == len(JobConfig.Series)
    mock_telemetry.assert_called_once_with(JobConfig.Telemetry.TELEMETRY)


@patch('hidrocli.jobs.runner.check_telemetry_job')
@patch('hidrocli.jobs.runner.check_series_job')
@patch('hidrocli.jobs.runner.check_base_job')
def test_run_skips_series_and_telemetry_together(mock_base, mock_series,
                                                 mock_telemetry, monkeypatch):
    _set_config(monkeypatch, SKIP_SERIES_JOBS=True)

    hidrocli.jobs.runner.run(hidrocli.jobs.runner.CONFIG)

    assert mock_base.call_count == len(JobConfig.Base)
    mock_series.assert_not_called()
    mock_telemetry.assert_not_called()


@patch('hidrocli.jobs.runner.check_telemetry_job')
@patch('hidrocli.jobs.runner.check_series_job')
@patch('hidrocli.jobs.runner.check_base_job')
def test_run_for_telemetria_skips_series(mock_base, mock_series,
                                         mock_telemetry, monkeypatch):
    _set_config(
        monkeypatch, SKIP_SERIES_JOBS=False, SKIP_FOR=(),
        RUN_FOR=(str(JobConfig.Telemetry.TELEMETRY),),
    )

    hidrocli.jobs.runner.run(hidrocli.jobs.runner.CONFIG)

    mock_series.assert_not_called()
    mock_telemetry.assert_called_once_with(JobConfig.Telemetry.TELEMETRY)


@patch('hidrocli.jobs.runner.check_telemetry_job')
@patch('hidrocli.jobs.runner.check_series_job')
@patch('hidrocli.jobs.runner.check_base_job')
def test_skip_for_telemetria_skips_only_telemetry(mock_base, mock_series,
                                                  mock_telemetry, monkeypatch):
    _set_config(
        monkeypatch, SKIP_SERIES_JOBS=False,
        SKIP_FOR=(str(JobConfig.Telemetry.TELEMETRY),), RUN_FOR=(),
    )

    hidrocli.jobs.runner.run(hidrocli.jobs.runner.CONFIG)

    assert mock_series.call_count == len(JobConfig.Series)
    mock_telemetry.assert_not_called()

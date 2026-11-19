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

from datetime import datetime, timedelta

import hidrocli.jobs
from hidrocli.config import setup_logger

setup_logger()

@patch('hidrocli.jobs.count_client')
@patch('hidrocli.jobs.add_token')
@patch('hidrocli.jobs.update_token')
@patch('hidrocli.jobs.get_credentials')
@patch('hidrocli.jobs.request_token')
@patch('hidrocli.jobs.get_token_model')
def test_get_token_add_new_token(mock_model,  mock_request, mock_creds,
                                 mock_update, mock_add,     mock_count):
    mock_model.return_value   = None
    mock_creds.return_value   = MagicMock(ID="test_id", Password="test_pass")
    mock_request.return_value = ("new_token", datetime.now() + timedelta(hours=1))
    mock_count.return_value   = 0

    result = hidrocli.jobs.get_token()

    mock_model.assert_called_once()
    mock_creds.assert_called_once()
    mock_request.assert_called_once_with("test_id", "test_pass")
    mock_count.assert_called_once()
    mock_update.assert_not_called()
    mock_add.assert_called_once()

    assert result == "new_token"

@patch('hidrocli.jobs.trigger_job')
@patch('hidrocli.jobs.insert_jobs')
@patch('hidrocli.jobs.count_job')
@pytest.mark.parametrize("job_config", [
    hidrocli.jobs.JobConfig.Base.BASIN,
    hidrocli.jobs.JobConfig.Base.SUB_BASIN,
    hidrocli.jobs.JobConfig.Base.ENTITY,
    hidrocli.jobs.JobConfig.Base.TOWNSHIP,
    hidrocli.jobs.JobConfig.Base.RIVER,
    hidrocli.jobs.JobConfig.Base.STATE,
])
def test_check_base_job(mock_count_jobs, mock_insert_jobs, mock_trigger_job, job_config):
    """TODO"""

    mock_count_jobs.side_effect = [0, 1, 1, 1, 0]
    hidrocli.jobs.check_base_job(job_config)
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

    from hidrocli.jobs import JobConfig, process_period
    result = process_period(station_code, start_date, end_date, JobConfig.Series.RAIN)

    assert len(result) == 1, f"Expected 1 job, got {len(result)}"
    assert result[0].Status == expected_status, \
        f"Expected status {expected_status}, got {result[0].Status}"
    assert result[0].StationID == station_code
    assert result[0].FromDate  == datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S")
    assert result[0].ToDate    == datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")


def test_process_period_returns_corrupted_for_future_date():
    """Test that future start date returns CORRUPTED."""

    from hidrocli.jobs import JobConfig, process_period
    future_date = (datetime.today() + timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S")
    result = hidrocli.jobs.process_period(123456, future_date, "2020-01-01 00:00:00", JobConfig.Series.RAIN)

    assert len(result) == 1
    assert result[0].Status == 4


def _load_json_file(job_config):
    with open(f'./tests/json/{job_config}.json') as f:
        import json;
        return json.load(f)


@pytest.mark.parametrize("job_config", [
    hidrocli.jobs.JobConfig.Base.BASIN,
    hidrocli.jobs.JobConfig.Series.RAIN,
])
def test_convert_json_items(job_config):
    items = hidrocli.jobs.convert_json_items(job_config, _load_json_file(job_config))
    match job_config:
        case hidrocli.jobs.JobConfig.Base.BASIN:
            for item in items:
                assert isinstance(item["Data_Ultima_Alteracao"], (datetime, type(None)))
                assert isinstance(item["Nome_Bacia"], str)
                assert isinstance(item["codigobacia"], int)
        case hidrocli.jobs.JobConfig.Series.RAIN:
            for item in items:
                for i in range(1, 32):
                    assert isinstance(item[f'Chuva_{i:02d}'], (float, type(None)))
                    assert isinstance(item[f'Chuva_{i:02d}_Status'], (int, type(None)))
                assert isinstance(item["Data_Ultima_Alteracao"], (datetime, type(None)))
                assert isinstance(item["Data_Hora_Dado"], (datetime, type(None)))
                assert isinstance(item["Maxima"], float)
                assert isinstance(item["Maxima_Status"], int)
                assert isinstance(item["Nivel_Consistencia"], int)
                assert isinstance(item["Numero_Dias_de_Chuva"], (int, type(None)))
                assert isinstance(item["Numero_Dias_de_Chuva_Status"], int)
                assert isinstance(item["Tipo_Medicao_Chuvas"], int)
                assert isinstance(item["Total"], float)
                assert isinstance(item["Total_Anual"], (float, type(None)))
                assert isinstance(item["Total_Anual_Status"], (int, type(None)))
                assert isinstance(item["Total_Status"], int)
                assert isinstance(item["codigoestacao"], int)


@pytest.mark.parametrize("job_config", [
    hidrocli.jobs.JobConfig.Series.RAIN,
])
def test_filter_repeated_series_items(job_config):
    items = hidrocli.jobs.convert_json_items(job_config, _load_json_file(job_config))
    filtered = hidrocli.jobs.filter_repeated_series_items(job_config, items)
    assert len(items) != len(filtered)


@patch('hidrocli.jobs.process_period')
def test_create_series_jobs_inserts_in_chunks(mock_period, monkeypatch):
    monkeypatch.setattr(hidrocli.jobs, "MAX_WORKERS", 2)
    monkeypatch.setattr(hidrocli.jobs, "BATCH_SIZE", 3)

    def fake_period(station, start, end, job_config):
        return [
            hidrocli.jobs.SeriesJobs(
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
        hidrocli.jobs, "insert_jobs_bulk",
        lambda jobs: chunks.append(len(jobs)),
    )

    stations = [
        [station, "2020-01-01 00:00:00", "2021-01-01 00:00:00"]
        for station in range(1, 6)
    ]
    hidrocli.jobs.create_series_jobs(
        stations, hidrocli.jobs.JobConfig.Series.RAIN
    )

    assert sum(chunks) == 10
    assert len(chunks) > 1
    assert all(size <= 4 for size in chunks)


@patch('hidrocli.jobs.count_job_by_status', return_value=[])
@patch('hidrocli.jobs.write_queue')
@patch('hidrocli.jobs.db_writer')
@patch('hidrocli.jobs.handle_job_request')
@patch('hidrocli.jobs.iter_jobs')
def test_trigger_job_streams_jobs(mock_iter, mock_handle, mock_writer,
                                  mock_queue, mock_count, monkeypatch):
    mock_iter.return_value = iter([
        MagicMock(ID=index) for index in range(20)
    ])
    monkeypatch.setattr(hidrocli.jobs, "MAX_WORKERS", 2)
    monkeypatch.setattr(hidrocli.jobs, "BATCH_SIZE", 5)

    hidrocli.jobs.trigger_job(
        hidrocli.jobs.JobConfig.Series.RAIN, ["filter"]
    )

    assert mock_handle.call_count == 20
    mock_iter.assert_called_once_with(
        hidrocli.jobs.JobConfig.Series.RAIN, ["filter"], 5
    )
    mock_queue.put.assert_called_once()


@patch('hidrocli.jobs.reset_series_job_dates', return_value=3)
@patch('hidrocli.jobs.get_period')
def test_update_series_job_uses_bulk_reset(mock_period, mock_reset,
                                           monkeypatch):
    mock_period.return_value.scalars.return_value.all.return_value = [1, 2, 3]
    monkeypatch.setattr(hidrocli.jobs, "BATCH_SIZE", 500)

    hidrocli.jobs.update_series_job(
        hidrocli.jobs.JobConfig.Series.RAIN
    )

    mock_reset.assert_called_once()
    args = mock_reset.call_args.args
    assert args[0] == hidrocli.jobs.JobConfig.Series.RAIN
    assert args[1] == [1, 2, 3]
    assert args[3] == 500

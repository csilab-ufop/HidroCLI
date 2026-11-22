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

import hidrocli.jobs.runner
from hidrocli.config import setup_logger

setup_logger()

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
    hidrocli.jobs.runner.JobConfig.Base.BASIN,
    hidrocli.jobs.runner.JobConfig.Series.RAIN,
])
def test_convert_json_items(job_config):
    items = hidrocli.jobs.runner.convert_json_items(job_config, _load_json_file(job_config))
    match job_config:
        case hidrocli.jobs.runner.JobConfig.Base.BASIN:
            for item in items:
                assert isinstance(item["Data_Ultima_Alteracao"], (datetime, type(None)))
                assert isinstance(item["Nome_Bacia"], str)
                assert isinstance(item["codigobacia"], int)
        case hidrocli.jobs.runner.JobConfig.Series.RAIN:
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


def test_convert_json_items_parses_all_supported_formats():
    items = hidrocli.jobs.runner.convert_json_items(
        hidrocli.jobs.runner.JobConfig.Series.RAIN,
        [
            {"Data": "2024-01-02 03:04:05.123456"},
            {"Data": "2024-01-02 03:04:05"},
            {"Data": "2024-01-02"},
            {"Data": "03:04:05"},
        ],
    )

    assert items[0]["Data"] == datetime(2024, 1, 2, 3, 4, 5, 123456)
    assert items[1]["Data"] == datetime(2024, 1, 2, 3, 4, 5)
    assert items[2]["Data"] == datetime(2024, 1, 2)
    assert items[3]["Data"].time() == datetime(1900, 1, 1, 3, 4, 5).time()


@pytest.mark.parametrize("job_config", [
    hidrocli.jobs.runner.JobConfig.Series.RAIN,
])
def test_filter_repeated_series_items(job_config):
    items = hidrocli.jobs.runner.normalize_items(str(job_config), _load_json_file(job_config))
    filtered = hidrocli.jobs.runner.filter_repeated_series_items(job_config, items)
    assert len(items) != len(filtered)


@patch('hidrocli.jobs.runner.process_period')
def test_create_series_jobs_inserts_in_chunks(mock_period, monkeypatch):
    monkeypatch.setattr(hidrocli.jobs.runner, "MAX_WORKERS", 2)
    monkeypatch.setattr(hidrocli.jobs.runner, "BATCH_SIZE", 3)
    monkeypatch.setattr(hidrocli.jobs.runner, "JOB_CHUNK_SIZE", 3)

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
    monkeypatch.setattr(hidrocli.jobs.runner, "MAX_WORKERS", 2)
    monkeypatch.setattr(hidrocli.jobs.runner, "BATCH_SIZE", 5)

    hidrocli.jobs.runner.trigger_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, ["filter"]
    )

    assert mock_handle.call_count == 20
    mock_iter.assert_called_once_with(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, ["filter"], 5
    )
    mock_queue.put.assert_called_once()


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.convert_json_items')
@patch('hidrocli.jobs.runner.request_job_data')
@patch('hidrocli.jobs.runner.get_token')
@pytest.mark.parametrize("save_json", [True, False])
@pytest.mark.parametrize("read_json", [True, False])
def test_handle_job_request_passes_json_flags(
        mock_token, mock_request, mock_convert, mock_queue,
        monkeypatch, save_json, read_json):
    monkeypatch.setattr(hidrocli.jobs.runner, "SAVE_JSON", save_json)
    monkeypatch.setattr(hidrocli.jobs.runner, "READ_JSON", read_json)
    monkeypatch.setattr(hidrocli.jobs.runner, "JSON_DIR", "custom/json")
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
@patch('hidrocli.jobs.runner.convert_json_items')
@patch('hidrocli.jobs.runner.request_job_data')
@patch('hidrocli.jobs.runner.get_token', return_value="token")
def test_handle_job_request_tags_items_with_job_id(
        mock_token, mock_request, mock_convert, mock_queue):
    items = [{"codigoestacao": 1}]
    mock_request.return_value = (True, items)
    mock_convert.side_effect = lambda config, value: value
    job = MagicMock()
    job.ID = 42
    job.to_params.return_value = {}

    hidrocli.jobs.runner.handle_job_request(
        job, hidrocli.jobs.runner.JobConfig.Base.BASIN
    )

    queued = mock_queue.put.call_args.args[0]
    assert queued.items[0]["_JobID"] == 42


@patch('hidrocli.jobs.runner.write_queue')
@patch('hidrocli.jobs.runner.request_job_data',
       side_effect=PermissionError("401"))
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
    monkeypatch.setattr(hidrocli.jobs.runner, "BATCH_SIZE", 500)

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
    monkeypatch.setattr(hidrocli.jobs.runner, "STATIONS", [2, 4])

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
    monkeypatch.setattr(hidrocli.jobs.runner, "STATIONS", stations)

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
    monkeypatch.setattr(hidrocli.jobs.runner, "STATIONS", [1, 99])

    hidrocli.jobs.runner.check_series_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    mock_create.assert_not_called()
    assert "99" in caplog.text


@patch('hidrocli.jobs.runner.create_job_filters', return_value=[])
@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.count_job', side_effect=[2, 0])
def test_trigger_series_jobs_retries_until_none(mock_count, mock_trigger,
                                                mock_filters):
    hidrocli.jobs.runner.trigger_series_jobs(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    assert mock_count.call_count == 2
    mock_trigger.assert_called_once_with(
        hidrocli.jobs.runner.JobConfig.Series.RAIN, []
    )


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
    monkeypatch.setattr(hidrocli.jobs.runner, "BATCH_SIZE", 100)

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
    monkeypatch.setattr(hidrocli.jobs.runner, "BATCH_SIZE", 100)
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
    monkeypatch.setattr(hidrocli.jobs.runner, "BATCH_SIZE", 100)
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


@patch('hidrocli.jobs.runner.trigger_series_jobs')
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
    monkeypatch.setattr(hidrocli.jobs.runner, "STATIONS", [])
    monkeypatch.setattr(
        hidrocli.jobs.runner, "INITIAL_DATE", datetime(2005, 1, 1)
    )
    monkeypatch.setattr(
        hidrocli.jobs.runner, "FINAL_DATE", datetime(2008, 1, 1)
    )

    hidrocli.jobs.runner.check_series_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    mock_create.assert_called_once()
    created = mock_create.call_args.args[0]
    assert created == [(1, datetime(2005, 1, 1), datetime(2008, 1, 1))]
    mock_update_windows.assert_called_once_with(
        hidrocli.jobs.runner.JobConfig.Series.RAIN,
        [(2, datetime(2005, 1, 1), datetime(2008, 1, 1))],
    )
    mock_update.assert_not_called()
    mock_trigger.assert_called_once()


@patch('hidrocli.jobs.runner.trigger_series_jobs')
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
    monkeypatch.setattr(hidrocli.jobs.runner, "STATIONS", [])
    monkeypatch.setattr(
        hidrocli.jobs.runner, "INITIAL_DATE", datetime(2005, 1, 1)
    )
    monkeypatch.setattr(hidrocli.jobs.runner, "FINAL_DATE", None)

    hidrocli.jobs.runner.check_series_job(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    mock_update.assert_called_once_with(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )


@patch('hidrocli.jobs.runner.create_job_filters', return_value=[])
@patch('hidrocli.jobs.runner.trigger_job')
@patch('hidrocli.jobs.runner.count_job', return_value=0)
def test_trigger_series_jobs_passes_date_bounds(
        mock_count, mock_trigger, mock_filters, monkeypatch):
    initial = datetime(2020, 1, 1)
    final   = datetime(2021, 1, 1)
    monkeypatch.setattr(hidrocli.jobs.runner, "INITIAL_DATE", initial)
    monkeypatch.setattr(hidrocli.jobs.runner, "FINAL_DATE", final)

    hidrocli.jobs.runner.trigger_series_jobs(
        hidrocli.jobs.runner.JobConfig.Series.RAIN
    )

    assert mock_filters.call_args.kwargs["initial_date"] == initial
    assert mock_filters.call_args.kwargs["final_date"] == final

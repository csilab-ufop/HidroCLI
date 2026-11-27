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

import os

import pytest
from unittest.mock import patch, Mock

import requests
import json

from datetime import datetime

from hidrocli.config import setup_logger
from hidrocli.webservices import (
    request_job_data, request_token,
    _request_hidro_ws, _json_file_path, _load_response,
)

setup_logger()

@patch('hidrocli.webservices.requests.get')
def test_request_hidro_ws_success(mock_get):
    """Test successful request returns JSON."""

    mock_response                   = Mock()
    mock_response.ok                = True
    mock_response.json.return_value = {"data": "test"}
    mock_get.return_value           = mock_response

    result = _request_hidro_ws("/endpoint", {"Authorization": "Bearer token"})

    assert result == {"data": "test"}
    mock_get.assert_called_once_with(
        "https://www.ana.gov.br/hidrowebservice/endpoint",
        headers={"Authorization": "Bearer token"},
        params={},
        timeout=300
    )


@pytest.mark.parametrize("status", [400, 401, 407, 417, 500, 504])
@patch('hidrocli.webservices.requests.get')
def test_request_hidro_ws_non_ok_raises(mock_get, status):
    """Any non-2xx status raises an HTTPError carrying the response."""

    mock_response                   = Mock()
    mock_response.ok                = False
    mock_response.status_code       = status
    mock_response.json.side_effect = ValueError("No JSON body")
    mock_get.return_value           = mock_response

    with pytest.raises(requests.exceptions.HTTPError) as excinfo:
        _request_hidro_ws("/endpoint", {})

    assert excinfo.value.response.status_code == status


@patch('hidrocli.webservices.requests.get')
def test_request_hidro_ws_timeout_raises(mock_get):
    """Test that a timeout is logged and re-raised."""

    mock_get.side_effect = requests.exceptions.Timeout

    with pytest.raises(requests.exceptions.Timeout):
        _request_hidro_ws("/endpoint", {})


@patch('hidrocli.webservices.logger')
@patch('hidrocli.webservices.requests.get')
def test_request_hidro_ws_timeout_logs_verbose(mock_get, mock_logger):
    """A timeout is an expected transient condition, not an ERROR."""

    mock_get.side_effect = requests.exceptions.ReadTimeout("read timed out")

    with pytest.raises(requests.exceptions.ReadTimeout):
        _request_hidro_ws("/endpoint", {})

    assert any(
        "timeout ReadTimeout" in str(call)
        for call in mock_logger.verbose.call_args_list
    )
    mock_logger.error.assert_not_called()


@patch('hidrocli.webservices.requests.get')
def test_request_hidro_ws_connection_error_raises(mock_get):
    """Test that a connection error is logged and re-raised."""

    mock_get.side_effect = requests.exceptions.ConnectionError(
        "Connection aborted.", ConnectionResetError(54, "Connection reset by peer")
    )

    with pytest.raises(requests.exceptions.ConnectionError):
        _request_hidro_ws("/endpoint", {})


@pytest.mark.parametrize("error", [
    requests.exceptions.ChunkedEncodingError("Response ended prematurely"),
    requests.exceptions.ContentDecodingError("Failed to decode response content"),
])
@patch('hidrocli.webservices.logger')
@patch('hidrocli.webservices.requests.get')
def test_request_hidro_ws_body_errors_log_trace(mock_get, mock_logger, error):
    """Premature or undecodable bodies are transient transport conditions."""

    mock_get.side_effect = error

    with pytest.raises(type(error)):
        _request_hidro_ws("/endpoint", {})

    assert any(
        type(error).__name__ in str(call)
        for call in mock_logger.trace.call_args_list
    )
    mock_logger.error.assert_not_called()


@patch('hidrocli.webservices.requests.get')
def test_request_hidro_ws_json_exception(mock_get):
    """Test handling of JSON decode error on successful response."""

    mock_response                  = Mock()
    mock_response.ok               = True
    mock_response.json.side_effect = ValueError("Invalid JSON")
    mock_get.return_value          = mock_response

    result = _request_hidro_ws("/endpoint", {})

    assert result is None


@patch('hidrocli.webservices._request_hidro_ws')
def test_request_token_success(mock_request):
    """Test successful token retrieval."""

    mock_request.return_value = {
        "items": {
            "tokenautenticacao": "abc123token",
            "validade": "Mon Jan 15 14:30:00 GMT-03:00 2024"
        }
    }

    result = request_token("client123", "pass456")

    assert result[0] == "abc123token"
    assert isinstance(result[1], datetime)
    assert result[1] == datetime(2024, 1, 15, 14, 30, 0)

    mock_request.assert_called_once_with(
        "/EstacoesTelemetricas/OAUth/v1",
        {
            "accept": "*/*",
            "Identificador": "client123",
            "Senha": "pass456"
        },
        {}
    )


@patch('hidrocli.webservices._request_hidro_ws')
@patch('hidrocli.webservices.time.sleep')
def test_request_token_retry_then_success(mock_sleep, mock_request):
    """Test retry logic when first attempt fails."""
    mock_request.side_effect = [
        Exception("Connection error"),
        {
            "items": {
                "tokenautenticacao": "token_after_retry",
                "validade": "Tue Feb 20 10:00:00 GMT-03:00 2024"
            }
        }
    ]

    result = request_token("client123", "pass456", max_retries=3, retry_delay=2)

    assert result[0]               == "token_after_retry"
    assert mock_request.call_count == 2
    mock_sleep.assert_called_once_with(2)


@patch('hidrocli.webservices._request_hidro_ws')
@patch('hidrocli.webservices.time.sleep')
def test_request_token_all_retries_fail(mock_sleep, mock_request):
    """Test that exception is raised after all retries fail."""

    with pytest.raises(Exception, match="Failed after"):
        request_token("client123", "pass456", max_retries=3, retry_delay=2)

    assert mock_request.call_count == 3
    assert mock_sleep.call_count   == 2


BASE_JOBS = ["Bacia", "SubBacia", "Entidade", "Municipio", "Rio", "Estado"]
SERIES_JOBS = ["Chuvas", "ResumoDescarga", "CurvaDescarga", "Sedimentos",
               "QualAgua", "Cotas", "Granulometria", "PerfilTransversal",
               "Vazoes"]
SERIES_PARAMS = {
    "Código da Estação":         "12345",
    "Tipo Filtro Data":          "DATA_LEITURA",
    "Data Inicial (yyyy-MM-dd)": "1927-05-01",
    "Data Final (yyyy-MM-dd)":   "1928-05-01",
}


def test_json_file_path_base_jobs():
    for job in BASE_JOBS:
        assert _json_file_path(job, {}, "json") == os.path.join(
            "json", f"{job}.json"
        )


def test_json_file_path_estacao():
    params = {"Unidade Federativa": "MG"}
    assert _json_file_path("Estacao", params, "json") == os.path.join(
        "json", "Estacao", "Estacao_MG.json"
    )


def test_json_file_path_series_jobs():
    expected = os.path.join(
        "json", "{job}", "station_12345_1927-05-01_1928-05-01.json"
    )
    for job in SERIES_JOBS:
        assert _json_file_path(job, SERIES_PARAMS, "json") == expected.format(job=job)


def test_load_response_returns_saved_payload(tmp_path):
    items = [{"codigobacia": "1", "Nome_Bacia": "RIO AMAZONAS"}]
    (tmp_path / "Bacia.json").write_text(json.dumps(items))

    assert _load_response("Bacia", {}, str(tmp_path)) == items


@patch('hidrocli.webservices._request_hidro_ws')
def test_request_job_data_unauthorized_raises(mock_request):
    """Test that a 401 is propagated so the caller can skip the job."""

    mock_request.side_effect = requests.exceptions.HTTPError(
        "401", response=Mock(status_code=401)
    )

    with pytest.raises(requests.exceptions.HTTPError):
        request_job_data("Bacia", "token", {})


@patch('hidrocli.webservices._request_hidro_ws')
def test_request_job_data_reads_json_without_request(mock_request, tmp_path):
    items = [{"codigobacia": "1"}]
    (tmp_path / "Bacia.json").write_text(json.dumps(items))

    success, result = request_job_data(
        "Bacia", "token", {}, json_dir=str(tmp_path), read_json=True
    )

    assert success is True
    assert result == items
    mock_request.assert_not_called()


@patch('hidrocli.webservices._save_response')
def test_request_job_data_does_not_save_loaded_payload(mock_save, tmp_path):
    items = [{"codigobacia": "1"}]
    (tmp_path / "Bacia.json").write_text(json.dumps(items))

    request_job_data(
        "Bacia", "token", {},
        save_json=True, json_dir=str(tmp_path), read_json=True,
    )

    mock_save.assert_not_called()


@patch('hidrocli.webservices._request_hidro_ws')
def test_request_job_data_read_json_falls_back_when_missing(mock_request,
                                                            tmp_path):
    items = [{"codigobacia": "1"}]
    mock_request.return_value = {"items": items}

    success, result = request_job_data(
        "Bacia", "token", {}, json_dir=str(tmp_path), read_json=True
    )

    assert success is True
    assert result == items
    mock_request.assert_called_once()


@patch('hidrocli.webservices._request_hidro_ws')
def test_request_job_data_read_json_falls_back_when_corrupt(mock_request,
                                                            tmp_path, caplog):
    (tmp_path / "Bacia.json").write_text("{not json")
    items = [{"codigobacia": "1"}]
    mock_request.return_value = {"items": items}

    success, result = request_job_data(
        "Bacia", "token", {}, json_dir=str(tmp_path), read_json=True
    )

    assert success is True
    assert result == items
    mock_request.assert_called_once()
    assert "requesting from API" in caplog.text


@patch('hidrocli.webservices._request_hidro_ws')
def test_request_job_data_saves_payload_after_read_fallback(mock_request,
                                                            tmp_path):
    items = [{"codigobacia": "1"}]
    mock_request.return_value = {"items": items}

    request_job_data(
        "Bacia", "token", {},
        save_json=True, json_dir=str(tmp_path), read_json=True,
    )

    assert json.loads((tmp_path / "Bacia.json").read_text()) == items


@patch('hidrocli.webservices._request_hidro_ws')
def test_request_job_data_saves_json(mock_request, tmp_path):
    items = [{"codigobacia": "1", "Nome_Bacia": "RIO AMAZONAS"}]
    mock_request.return_value = {"items": items}

    success, result = request_job_data(
        "Bacia", "token", {}, save_json=True, json_dir=str(tmp_path)
    )

    assert success is True
    assert result == items
    path = tmp_path / "Bacia.json"
    assert json.loads(path.read_text()) == items
    assert path.read_text().startswith("[\n  {")


@patch('hidrocli.webservices._request_hidro_ws')
def test_request_job_data_creates_series_directory(mock_request, tmp_path):
    mock_request.return_value = {"items": [{"codigoestacao": "12345"}]}

    request_job_data(
        "Chuvas", "token", SERIES_PARAMS, save_json=True, json_dir=str(tmp_path)
    )

    path = tmp_path / "Chuvas" / "station_12345_1927-05-01_1928-05-01.json"
    assert path.is_file()
    assert json.loads(path.read_text()) == [{"codigoestacao": "12345"}]


@patch('hidrocli.webservices._request_hidro_ws')
def test_request_job_data_saves_empty_items(mock_request, tmp_path):
    mock_request.return_value = {"items": []}

    success, items = request_job_data(
        "Bacia", "token", {}, save_json=True, json_dir=str(tmp_path)
    )

    assert success is True
    assert items == []
    assert (tmp_path / "Bacia.json").read_text().strip() == "[]"


@patch('hidrocli.webservices._request_hidro_ws')
def test_request_job_data_does_not_save_when_disabled(mock_request, tmp_path,
                                                      monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_request.return_value = {"items": [{"codigobacia": "1"}]}

    request_job_data(
        "Bacia", "token", {}, save_json=False, json_dir=str(tmp_path / "json")
    )

    assert list(tmp_path.iterdir()) == []


@patch('hidrocli.webservices._save_response', side_effect=OSError("disk full"))
@patch('hidrocli.webservices._request_hidro_ws')
def test_request_job_data_save_failure_keeps_data(mock_request,
                                                  mock_save_response):
    items = [{"codigobacia": "1"}]
    mock_request.return_value = {"items": items}

    success, result = request_job_data(
        "Bacia", "token", {}, save_json=True, json_dir="json"
    )

    assert success is True
    assert result == items
    mock_save_response.assert_called_once()


TELEMETRY_PARAMS = {
    "Código da Estação":          12345,
    "Tipo Filtro Data":           "DATA_LEITURA",
    "Data de Busca (yyyy-MM-dd)": "2024-05-28",
    "Range Intervalo de busca":   "DIAS_30",
}


def test_json_file_path_telemetry():
    assert _json_file_path("Telemetria", TELEMETRY_PARAMS, "json") == os.path.join(
        "json", "Telemetria", "station_12345_2024-05-28_DIAS_30.json"
    )


@patch('hidrocli.webservices._request_hidro_ws')
def test_request_job_data_saves_telemetry_json(mock_request, tmp_path):
    items = [{"codigoestacao": "12345", "Data_Hora_Medicao": "2024-05-28"}]
    mock_request.return_value = {"items": items}

    success, result = request_job_data(
        "Telemetria", "token", TELEMETRY_PARAMS,
        save_json=True, json_dir=str(tmp_path),
    )

    assert success is True
    assert result == items
    path = (
        tmp_path / "Telemetria"
        / "station_12345_2024-05-28_DIAS_30.json"
    )
    assert json.loads(path.read_text()) == items


def test_telemetry_endpoint_is_registered():
    from hidrocli.webservices import _DATA_ENDPOINTS_MAP

    assert _DATA_ENDPOINTS_MAP["Telemetria"] == (
        "/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaDetalhada/v1"
    )

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

import pytest
from hidrocli.models.client import *


def _series_job():
    return SeriesJobs(
        HidroTable="Chuvas",
        StationID=1,
        FromDate=datetime(2024, 1, 1),
        ToDate=datetime(2024, 12, 31),
        Status=1,
    )


def test_series_jobs_defaults_to_last_update_filter():
    params = _series_job().to_params()

    assert params["Tipo Filtro Data"] == "DATA_ULTIMA_ATUALIZACAO"


def test_series_jobs_accepts_filter_override():
    params = _series_job().to_params("DATA_LEITURA")

    assert params["Tipo Filtro Data"] == "DATA_LEITURA"


def test_base_and_station_jobs_ignore_filter():
    assert BaseJobs().to_params("DATA_LEITURA") == {}
    assert StationJobs(UF="MG").to_params("DATA_LEITURA") == {
        "Unidade Federativa": "MG"
    }


def _telemetry_job():
    return TelemetryJobs(
        HidroTable="Telemetria",
        StationID=12345,
        Date=datetime(2024, 5, 28),
        Range="DIAS_30",
        Status=1,
    )


def test_telemetry_jobs_params():
    params = _telemetry_job().to_params("DATA_LEITURA")

    assert params == {
        "Código da Estação":          12345,
        "Tipo Filtro Data":           "DATA_LEITURA",
        "Data de Busca (yyyy-MM-dd)": "2024-05-28",
        "Range Intervalo de busca":   "DIAS_30",
    }


def test_telemetry_jobs_iterates_all_fields():
    job = _telemetry_job()
    job.ID = 7
    job.Retries = 2

    fields = dict(job)

    assert fields == {
        "ID":         7,
        "HidroTable": "Telemetria",
        "Status":     1,
        "StationID":  12345,
        "Date":       datetime(2024, 5, 28),
        "Range":      "DIAS_30",
        "Retries":    2,
    }


def test_dummy():
    assert True

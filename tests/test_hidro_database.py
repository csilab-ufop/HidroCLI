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
from unittest.mock import patch

from datetime import datetime

from hidrocli.config import setup_logger
from hidrocli.database import *
from hidrocli.database import _setup_db
from hidrocli.database.hidro import *
from hidrocli.jobs.runner import JobConfig, write_data
from hidrocli.models.hidro import (
    DischargeMeasurement, Rain, WaterQuality, WaterQualityStatus,
)

setup_logger()


def _count_rows(model):
    """Count rows for *model* using the patched Hidro connection."""
    import hidrocli.database.hidro as hidro
    session = hidro.HIDRO_DB.get_session()
    try:
        return session.query(model).count()
    finally:
        session.close()


@pytest.fixture
def hidro_db(tmp_path):

    db_path = str(tmp_path / "hidro.db")
    db_type = DatabaseType.HIDRO
    connection = _setup_db(db_path, db_type)
    with patch('hidrocli.database.hidro.HIDRO_DB', connection):
        yield connection
        HidroBase.metadata.drop_all(connection.engine)
        connection.close()


def test_upsert_items_updates_existing_rows_in_bulk(hidro_db):
    insert_hidro([
        Rain(EstacaoCodigo=station, Data=datetime(2024, 1, 1), Total=0.0)
        for station in range(1, 121)
    ])

    assert upsert_items(
        "Chuvas",
        normalize_items("Chuvas", [
            {
                "codigoestacao":    station,
                "Data_Hora_Dado":   datetime(2024, 1, 1),
                "Total":            float(station),
            }
            for station in range(1, 121)
        ]),
    ) == 0
    session = hidro_db.get_session()
    try:
        assert session.query(Rain).filter(Rain.Total == 0.0).count() == 0
        assert session.query(Rain).filter(Rain.Total == 120.0).count() == 1
    finally:
        session.close()


def test_discharge_summary_verify_keys_cover_the_measurement(hidro_db):
    keys = get_verify_keys("ResumoDescarga")

    assert set(keys) == {
        "EstacaoCodigo", "Data", "NivelConsistencia", "Profundidade",
        "AreaMolhada", "Cota", "Largura", "Vazao", "VelMedia",
    }
    assert "DataAlt" not in keys


def test_cross_section_verify_keys_use_ana_id():
    assert get_verify_keys("PerfilTransversal") == {
        "ANA_RegistroID": "ANA_RegistroID",
    }


def test_qual_agua_status_verify_keys_use_internal_id():
    assert get_verify_keys("QualAguaStatus") == {
        "QualAguaID": "QualAguaID",
    }


def test_upsert_items_keeps_distinct_discharge_measurements(hidro_db):
    insert_hidro([
        DischargeMeasurement(
            EstacaoCodigo=1,
            Data=datetime(2024, 1, 1),
            NivelConsistencia=1,
            Profundidade=1.0,
            AreaMolhada=2.0,
            Cota=3.0,
            Largura=4.0,
            Vazao=5.0,
            VelMedia=6.0,
        ),
    ])

    assert upsert_items(
        "ResumoDescarga",
        normalize_items("ResumoDescarga", [{
            "codigoestacao":     1,
            "Data_Hora_Dado":    datetime(2024, 1, 1),
            "Nivel_Consistencia": 1,
            "Profundidade (m)":  1.0,
            "Area_Molhada (m2)": 2.0,
            "Cota (cm)":         3.0,
            "Largura (m)":       4.0,
            "Vazao (m3/s)":      9.0,
            "Vel_Media (m/s)":   6.0,
        }]),
    ) == 1

    assert _count_rows(DischargeMeasurement) == 2
    session = hidro_db.get_session()
    try:
        assert session.query(DischargeMeasurement).filter_by(Vazao=9.0).count() == 1
    finally:
        session.close()


def test_write_data_reuses_existing_qual_agua_registro_id(hidro_db):
    item = {
        "codigoestacao":  1,
        "Data_Hora_Dado": datetime(2024, 1, 1),
    }

    write_data(JobConfig.Series.WATER_QUALITY, [], normalize_items("QualAgua", [dict(item)]))
    write_data(JobConfig.Series.WATER_QUALITY, [], normalize_items("QualAgua", [dict(item)]))

    assert _count_rows(WaterQuality) == 1
    assert _count_rows(WaterQualityStatus) == 1


def test_upsert_items_spans_multiple_chunks(hidro_db):
    items = [
        {
            "codigoestacao":  station,
            "Data_Hora_Dado": datetime(2024, 1, 1),
            "Total":          float(station),
        }
        for station in range(1, 2501)
    ]

    assert upsert_items("Chuvas", normalize_items("Chuvas", items)) == 2500
    assert _count_rows(Rain) == 2500

    assert upsert_items("Chuvas", normalize_items("Chuvas", items)) == 0
    assert _count_rows(Rain) == 2500


def test_upsert_items_inserts_new_and_updates_existing(hidro_db):
    insert_hidro([
        Rain(EstacaoCodigo=1, Data=datetime(2024, 1, 1), Total=10.0),
    ])

    assert upsert_items(
        "Chuvas",
        normalize_items("Chuvas", [
            {
                "codigoestacao":  1,
                "Data_Hora_Dado": datetime(2024, 1, 1),
                "Total":          42.0,
            },
            {
                "codigoestacao":  2,
                "Data_Hora_Dado": datetime(2024, 1, 1),
                "Total":          7.0,
            },
        ]),
    ) == 1

    session = hidro_db.get_session()
    try:
        first = session.query(Rain).filter(Rain.EstacaoCodigo == 1).one()
        assert first.Total == 42.0
        second = session.query(Rain).filter(Rain.EstacaoCodigo == 2).one()
        assert second.Total == 7.0
        assert session.query(Rain).count() == 2
    finally:
        session.close()


def test_get_telemetry_stations_filters_by_code(hidro_db):
    insert_hidro([
        Station(
            Codigo=1,
            PeriodoTelemetricaInicio=datetime(2024, 1, 1),
            PeriodoTelemetricaFim=datetime(2024, 2, 1),
        ),
        Station(
            Codigo=2,
            PeriodoTelemetricaInicio=datetime(2024, 3, 1),
            PeriodoTelemetricaFim=None,
        ),
        Station(Codigo=3, PeriodoTelemetricaInicio=None),
    ])

    rows = get_telemetry_stations([2, 3])

    assert [(row[0], row[1], row[2]) for row in rows] == [
        (2, datetime(2024, 3, 1), None),
    ]


def test_get_telemetry_stations_returns_all_with_period(hidro_db):
    insert_hidro([
        Station(Codigo=1, PeriodoTelemetricaInicio=datetime(2024, 1, 1)),
        Station(Codigo=2, PeriodoTelemetricaInicio=datetime(2024, 2, 1)),
        Station(Codigo=3, PeriodoTelemetricaInicio=None),
    ])

    rows = get_telemetry_stations()

    assert [row[0] for row in rows] == [1, 2]

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
from unittest.mock import patch

import pytest

from hidrocli.config import setup_logger
from hidrocli.database import DatabaseType, _setup_db
from hidrocli.database.client import upsert_job_records
from hidrocli.jobs import (
    JobConfig, filter_repeated_series_items, write_data,
)
from hidrocli.models.client import ClientBase, JobRecords
from hidrocli.models.hidro import (
    Basin, CrossSection, HidroBase, Rain, VerticalCrossSection,
    WaterQuality, WaterQualityStatus,
)

setup_logger()


@pytest.fixture
def hidro_db(tmp_path):
    connection = _setup_db(str(tmp_path / "hidro.db"), DatabaseType.HIDRO)
    with patch("hidrocli.database.hidro.HIDRO_DB", connection):
        yield connection
        HidroBase.metadata.drop_all(connection.engine)
        connection.close()


@pytest.fixture
def client_db(tmp_path):
    connection = _setup_db(str(tmp_path / "client.db"), DatabaseType.CLIENT)
    with patch("hidrocli.database.client.CLIENT_DB", connection):
        yield connection
        ClientBase.metadata.drop_all(connection.engine)
        connection.close()


def test_upsert_job_records_updates_latest_job(client_db):
    upsert_job_records([{
        "JobID":     1,
        "JobName":   "Chuvas",
        "DataTable": "Chuvas",
        "DataID":    10,
    }])
    upsert_job_records([{
        "JobID":     2,
        "JobName":   "Chuvas",
        "DataTable": "Chuvas",
        "DataID":    10,
    }])

    session = client_db.get_session()
    try:
        records = session.query(JobRecords).all()
        assert len(records) == 1
        assert records[0].JobID == 2
        assert records[0].DataIns is not None
        assert records[0].DataAlt is not None
    finally:
        session.close()


def test_write_data_records_base_provenance(hidro_db, client_db):
    item = {
        "codigobacia": 1,
        "Nome_Bacia":  "Test basin",
        "_JobID":      5,
    }

    write_data(JobConfig.Base.BASIN, [], [dict(item)])

    hidro_session = hidro_db.get_session()
    try:
        basin = hidro_session.query(Basin).one()
        basin_id = basin.RegistroID
    finally:
        hidro_session.close()

    session = client_db.get_session()
    try:
        record = session.query(JobRecords).one()
        assert record.JobID == 5
        assert record.JobName == "Bacia"
        assert record.DataTable == "Bacia"
        assert record.DataID == basin_id
    finally:
        session.close()


def test_write_data_records_series_provenance(hidro_db, client_db):
    item = {
        "codigoestacao":  1,
        "Data_Hora_Dado": datetime(2024, 1, 1),
        "Total":          10.0,
        "_JobID":         7,
    }

    write_data(JobConfig.Series.RAIN, [], [dict(item)])
    write_data(JobConfig.Series.RAIN, [], [
        {**item, "Total": 20.0, "_JobID": 8},
    ])

    hidro_session = hidro_db.get_session()
    try:
        rain = hidro_session.query(Rain).one()
        rain_id = rain.RegistroID
        assert rain.Total == 20.0
    finally:
        hidro_session.close()

    session = client_db.get_session()
    try:
        records = session.query(JobRecords).all()
        assert len(records) == 1
        assert records[0].JobID == 8
        assert records[0].JobName == "Chuvas"
        assert records[0].DataTable == "Chuvas"
        assert records[0].DataID == rain_id
    finally:
        session.close()


def test_write_data_records_water_quality_status_provenance(hidro_db, client_db):
    item = {
        "codigoestacao":  1,
        "Data_Hora_Dado": datetime(2024, 1, 1),
        "_JobID":         9,
    }

    write_data(JobConfig.Series.WATER_QUALITY, [], [dict(item)])

    session = client_db.get_session()
    try:
        records = session.query(JobRecords).all()
        assert {record.DataTable for record in records} == {
            "QualAgua", "QualAguaStatus",
        }
        for record in records:
            assert record.JobID == 9
            assert record.JobName == "QualAgua"
    finally:
        session.close()


def test_write_data_records_cross_section_verticals(hidro_db, client_db):
    item = {
        "Registro_ID":        67386491.0,
        "codigoestacao":      1,
        "Nivel_Consistencia": 1,
        "Data_Hora_Medicao":  datetime(2024, 1, 1),
        "Num_Levantamento":   1,
        "Tipo_Secao":         1,
        "Num_Verticais":      1,
        "Distancia_pipf":     10.0,
        "Eixo_X_Dist_Maxima": 10.0,
        "Eixo_X_Dist_Minima": 0.0,
        "Eixo_Y_Cota_Maxima": 100.0,
        "Eixo_Y_Cota_Minima": 0.0,
        "Elm_Geom_Passo_Cota": 10.0,
        "Observacoes":        "",
        "Cota":               50.0,
        "Distancia":          5.0,
        "_JobID":             11,
    }

    write_data(JobConfig.Series.CROSS_SECTION, [], [dict(item)])

    hidro_session = hidro_db.get_session()
    try:
        cross_section = hidro_session.query(CrossSection).one()
        parent_id = cross_section.RegistroID
        assert cross_section.ANA_RegistroID == 67386491.0
        vertical = hidro_session.query(VerticalCrossSection).one()
        vertical_id = vertical.RegistroID
        assert vertical.PerfilTransversalID == parent_id
    finally:
        hidro_session.close()

    session = client_db.get_session()
    try:
        records = {
            record.DataTable: record
            for record in session.query(JobRecords).all()
        }
        assert set(records) == {"PerfilTransversal", "PerfilTransversalVert"}
        assert records["PerfilTransversal"].DataID == parent_id
        assert records["PerfilTransversalVert"].DataID == vertical_id
        for record in records.values():
            assert record.JobID == 11
            assert record.JobName == "PerfilTransversal"
    finally:
        session.close()


def test_cross_section_skips_missing_ana_id(hidro_db, client_db):
    item = {
        "codigoestacao":      1,
        "Nivel_Consistencia": 1,
        "Data_Hora_Medicao":  datetime(2024, 1, 1),
        "Num_Levantamento":   1,
        "Tipo_Secao":         1,
        "Num_Verticais":      1,
        "Distancia_pipf":     10.0,
        "Eixo_X_Dist_Maxima": 10.0,
        "Eixo_X_Dist_Minima": 0.0,
        "Eixo_Y_Cota_Maxima": 100.0,
        "Eixo_Y_Cota_Minima": 0.0,
        "Elm_Geom_Passo_Cota": 10.0,
        "Observacoes":        "",
        "Cota":               50.0,
        "Distancia":          5.0,
        "_JobID":             11,
    }

    write_data(JobConfig.Series.CROSS_SECTION, [], [dict(item)])

    hidro_session = hidro_db.get_session()
    try:
        assert hidro_session.query(CrossSection).count() == 0
        assert hidro_session.query(VerticalCrossSection).count() == 0
    finally:
        hidro_session.close()


def test_cross_section_keeps_distinct_ana_ids_with_same_natural_key(
        hidro_db, client_db):
    def item(ana_id, registro_id, cota, distancia):
        return {
            "Registro_ID":        ana_id,
            "codigoestacao":      1,
            "Nivel_Consistencia": 1,
            "Data_Hora_Medicao":  datetime(2024, 1, 1),
            "Num_Levantamento":   1,
            "Tipo_Secao":         1,
            "Num_Verticais":      1,
            "Distancia_pipf":     10.0,
            "Eixo_X_Dist_Maxima": 10.0,
            "Eixo_X_Dist_Minima": 0.0,
            "Eixo_Y_Cota_Maxima": 100.0,
            "Eixo_Y_Cota_Minima": 0.0,
            "Elm_Geom_Passo_Cota": 10.0,
            "Observacoes":        "",
            "Cota":               cota,
            "Distancia":          distancia,
            "_JobID":             registro_id,
        }

    write_data(JobConfig.Series.CROSS_SECTION, [], [
        item(111.0, 1, 50.0, 5.0),
        item(222.0, 2, 60.0, 6.0),
    ])

    hidro_session = hidro_db.get_session()
    try:
        assert hidro_session.query(CrossSection).count() == 2
        assert hidro_session.query(VerticalCrossSection).count() == 2
    finally:
        hidro_session.close()


def test_water_quality_status_uses_local_qual_agua_id(hidro_db, client_db):
    item = {
        "codigoestacao":  1,
        "Data_Hora_Dado": datetime(2024, 1, 1),
        "_JobID":         9,
    }

    write_data(JobConfig.Series.WATER_QUALITY, [], [dict(item)])

    hidro_session = hidro_db.get_session()
    try:
        measurement = hidro_session.query(WaterQuality).one()
        status = hidro_session.query(WaterQualityStatus).one()
        assert status.QualAguaID == measurement.RegistroID
    finally:
        hidro_session.close()


def test_filter_repeated_discharge_summary_ignores_job_tag():
    items = [
        {
            "codigoestacao":  1,
            "Data_Hora_Dado": datetime(2024, 1, 1),
            "_JobID":         1,
        },
        {
            "codigoestacao":  1,
            "Data_Hora_Dado": datetime(2024, 1, 1),
            "_JobID":         2,
        },
    ]

    filtered = filter_repeated_series_items(
        JobConfig.Series.DISCHARGE_SUMMARY, items)

    assert len(filtered) == 1

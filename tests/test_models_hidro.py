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
from hidrocli.models.hidro import *
from hidrocli.models.hidro import Granulometry


def test_granulometry_maps_inicial_and_final_times_in_order():
    sample = Granulometry.from_json({
        "HoraInicial": "08:30:00",
        "HoraFinal":   "09:45:00",
    })

    assert sample.HoraInicial == "08:30:00"
    assert sample.HoraFinal   == "09:45:00"


def test_cross_section_keeps_ana_id_as_audit_data():
    sample = CrossSection.from_json({
        "ANA_RegistroID":        67386491.0,
        "EstacaoCodigo":         1,
        "NivelConsistencia":     1,
        "Data":                  datetime(2024, 1, 1),
        "DataAlt":               datetime(2024, 2, 1),
        "NumLevantamento":       1,
    })

    assert sample.RegistroID is None
    assert sample.ANA_RegistroID == 67386491.0
    assert sample.DataAlt == datetime(2024, 2, 1)


def test_vertical_cross_section_uses_internal_parent_id():
    sample = VerticalCrossSection.from_json({
        "Registro_ID": 67386491.0,
        "Cota":        50.0,
        "Distancia":   5.0,
    }, 7)

    assert sample.PerfilTransversalID == 7
    assert sample.Cota == 50.0
    assert sample.Distancia == 5.0


def test_water_quality_status_uses_qual_agua_id():
    sample = WaterQualityStatus.from_json({
        "QualAguaID":          5,
        "QualAgua001Status":   1,
    })

    assert sample.QualAguaID == 5
    assert sample.QualAgua001Status == 1


def test_telemetry_maps_measurement_fields():
    sample = Telemetry.from_json({
        "EstacaoCodigo":          12345,
        "Data_Hora_Medicao":      datetime(2024, 5, 28),
        "Data_Atualizacao":       datetime(2024, 5, 29),
        "Bateria":                12.6,
        "Cota_Sensor":            1114.3,
        "Cota_Sensor_Status":     1,
        "Chuva_Acumulada":        1.2,
        "Chuva_Acumulada_Status": 1,
        "Vazao_Adotada":          87.12,
        "Vazao_Adotada_Status":   1,
    })

    assert sample.EstacaoCodigo == 12345
    assert sample.Data_Hora_Medicao == datetime(2024, 5, 28)
    assert sample.Data_Atualizacao == datetime(2024, 5, 29)
    assert sample.Bateria == 12.6
    assert sample.Cota_Sensor == 1114.3
    assert sample.Cota_Sensor_Status == 1
    assert sample.Chuva_Acumulada == 1.2
    assert sample.Chuva_Acumulada_Status == 1
    assert sample.Vazao_Adotada == 87.12
    assert sample.Vazao_Adotada_Status == 1


def test_telemetry_verify_keys_use_station_and_measurement_time():
    from hidrocli.database import get_verify_keys

    assert get_verify_keys("Telemetria") == {
        "EstacaoCodigo":     "EstacaoCodigo",
        "Data_Hora_Medicao": "Data_Hora_Medicao",
    }


def test_dummy():
    assert True

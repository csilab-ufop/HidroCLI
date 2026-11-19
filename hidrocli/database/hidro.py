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

import logging
logger = logging.getLogger(__name__)

from typing import List

from sqlalchemy import select

from hidrocli.models.hidro  import *

HIDRO_DB = None

_HIDRO_MODELS_MAP = {
    "Bacia":                 Basin,
    "SubBacia":              SubBasin,
    "Entidade":              Entity,
    "Municipio":             Township,
    "Rio":                   River,
    "Estado":                State,
    "Estacao":               Station,
    "Chuvas":                Rain,
    "ResumoDescarga":        DischargeMeasurement,
    "CurvaDescarga":         RatingCurve,
    "Sedimentos":            Sediments,
    "QualAgua":              WaterQuality,
    "QualAguaStatus":        WaterQualityStatus,
    "Cotas":                 Stage,
    "Granulometria":         Granulometry,
    "PerfilTransversal":     CrossSection,
    "PerfilTransversalVert": VerticalCrossSection,
    "Vazoes":                FlowRate,
}


def get_hidro_model(name: str):
    return _HIDRO_MODELS_MAP[name]


def insert_hidro(collection: List[HidroBase], expire = True) -> List[HidroBase]:
    """ Insert a list of Hidro ORM Model into Hidro Database"""

    hidro_session = HIDRO_DB.get_session()
    hidro_session.expire_on_commit = expire
    hidro_session.add_all(collection)
    hidro_session.flush()
    hidro_session.commit()
    hidro_session.close()
    return collection


def count_hidro(model: HidroBase):
    """ Counts a given Model in Hidro Database. """

    hidro_session = HIDRO_DB.get_session()
    count_model   = hidro_session.query(model).count()
    hidro_session.close()
    return count_model


def get_states() -> State:
    """ Returns registered States in Hidro Database. """

    hidro_session = HIDRO_DB.get_session()
    states = hidro_session.query(State).filter(State.CodigoIBGE.isnot(None)).all()
    hidro_session.close()
    return states


def get_period(model_name: str, only_code=False, with_null_end_date=False):
    """ Returns stations with initial and final periods for an given table in Hidro Database. """

    statement = create_period_statement(model_name, only_code, with_null_end_date)
    hidro_session = HIDRO_DB.get_session()
    period_data = hidro_session.execute(statement)
    hidro_session.close()
    return period_data


def create_period_statement(model_name, only_code: bool, with_null_end_date: bool):
    columns = [Station.Codigo]
    match model_name:
        case "Chuvas":
            if not only_code:
                columns.extend([Station.PeriodoRegistradorChuvaInicio, Station.PeriodoRegistradorChuvaFim])
            statement = select(*columns).where(Station.PeriodoRegistradorChuvaInicio.isnot(None))
            if with_null_end_date:
                statement = statement.where(Station.PeriodoRegistradorChuvaFim.is_(None))
        case ("ResumoDescarga" | "CurvaDescarga" | "PerfilTransversal" | "Vazoes"):
            if not only_code:
                columns.extend([Station.PeriodoDescLiquidaInicio, Station.PeriodoDescLiquidaFim])
            statement = select(*columns).where(Station.PeriodoDescLiquidaInicio.isnot(None))
            if with_null_end_date:
                statement = statement.where(Station.PeriodoDescLiquidaFim.is_(None))
        case ("Sedimentos" | "Granulometria"):
            if not only_code:
                columns.extend([Station.PeriodoSedimentosInicio, Station.PeriodoSedimentosFim])
            statement = select(*columns).where(Station.PeriodoSedimentosInicio.isnot(None))
            if with_null_end_date:
                statement = statement.where(Station.PeriodoSedimentosFim.is_(None))
        case "Cotas":
            if not only_code:
                columns.extend([Station.PeriodoRegistradorNivelInicio, Station.PeriodoRegistradorNivelFim])
            statement = select(*columns).where(Station.PeriodoRegistradorNivelInicio.isnot(None))
            if with_null_end_date:
                statement = statement.where(Station.PeriodoRegistradorNivelFim.is_(None))
        case "QualAgua":
            if not only_code:
                columns.extend([Station.PeriodoQualAguaInicio, Station.PeriodoQualAguaFim])
            statement = select(*columns).where(Station.PeriodoQualAguaInicio.isnot(None))
            if with_null_end_date:
                statement = statement.where(Station.PeriodoQualAguaFim.is_(None))
    # print(type(statement))
    # sqlalchemy.sql.selectable.Select
    return statement


def _updated_mapping(model, item):
    """Return bulk-update values for an existing row, excluding identity."""

    mapped = model.from_json(item)
    return {
        column.key: getattr(mapped, column.key)
        for column in model.__table__.columns
        if column.key not in ("RegistroID", "DataIns")
    }


def handle_batch_update(job_name: str, items):
    """Upsert ``items`` into the job's Hidro model.

    Only the key columns are read for existing rows; updates are sent through
    ORM bulk mappings and committed once per chunk. This keeps memory flat and
    makes repeated loads actually update existing rows.

    Returns the list of newly created rows (not yet inserted).
    """

    hidro_session = HIDRO_DB.get_session()
    model         = get_hidro_model(job_name)
    verify_keys   = get_verify_keys(job_name)
    chunk_size    = max(1, 800 // max(1, len(verify_keys)))
    key_columns   = [getattr(model, key) for key in verify_keys]
    new_entries   = []
    processed     = set()

    try:
        for start in range(0, len(items), chunk_size):
            chunk = items[start:start + chunk_size]

            filters = [
                getattr(model, model_key).in_(
                    [item.get(json_key) for item in chunk]
                )
                for model_key, json_key in verify_keys.items()
            ]
            rows = (
                hidro_session.query(model.RegistroID, *key_columns)
                .filter(*filters)
                .all()
            )
            existing = {tuple(row[1:]): row[0] for row in rows}

            updates = []
            for item in chunk:
                key = tuple(item.get(verify_keys[k]) for k in verify_keys)
                if key in processed:
                    continue
                processed.add(key)

                row_id = existing.get(key)
                if row_id is None:
                    new_entries.append(model.from_json(item))
                    continue

                mapping = _updated_mapping(model, item)
                mapping["RegistroID"] = row_id
                updates.append(mapping)

            if updates:
                hidro_session.bulk_update_mappings(model, updates)
                hidro_session.commit()
                logger.verbose(
                    f"Updated {len(updates)} {model.__tablename__} rows."
                )
    finally:
        hidro_session.close()
    return new_entries


def get_qual_agua_ids(items):
    """Return existing QualAgua ``(station, date) -> RegistroID`` mappings."""

    if not items:
        return {}

    codes = list({item["codigoestacao"] for item in items})
    dates = list({item["Data_Hora_Dado"] for item in items})

    hidro_session = HIDRO_DB.get_session()
    try:
        rows = hidro_session.query(WaterQuality).filter(
            WaterQuality.EstacaoCodigo.in_(codes),
            WaterQuality.Data.in_(dates),
        ).all()
        return {
            (row.EstacaoCodigo, row.Data): row.RegistroID
            for row in rows
        }
    finally:
        hidro_session.close()


def get_verify_keys(name: str):
    match name:
        case ("Bacia"     | "SubBacia" | "Entidade" |
              "Municipio" | "Rio"      | "Estacao"):
            return {"Codigo": f"codigo{name.lower()}"}
        case "Estado":
            return {"Codigo": "codigouf"}
        case ("Chuvas" | "Vazoes" | "Sedimentos" | "Cotas"):
            return {'EstacaoCodigo': 'codigoestacao',
                    'Data': 'Data_Hora_Dado'}
        case "ResumoDescarga":
            return {
                'EstacaoCodigo':     'codigoestacao',
                'Data':              'Data_Hora_Dado',
                'NivelConsistencia': 'Nivel_Consistencia',
                'Profundidade':      'Profundidade (m)',
                'AreaMolhada':       'Area_Molhada (m2)',
                'Cota':              'Cota (cm)',
                'Largura':           'Largura (m)',
                'Vazao':             'Vazao (m3/s)',
                'VelMedia':          'Vel_Media (m/s)',
            }
        case "Granulometria":
            return {'EstacaoCodigo': 'codigoestacao',
                    'Data': 'Data_Dado',
                    'HoraInicial': 'Hora_Inicial',
                    'HoraFinal': 'Hora_Final'}
        case "CurvaDescarga":
            return {'EstacaoCodigo': 'codigoestacao',
                    'NumeroCurva': 'Numero_Curva',
                    'PeriodoValidadeInicio': 'Periodo_Validade_Inicio',
                    'PeriodoValidadeFim': 'Periodo_Validade_Fim'}
        case "QualAgua":
            return {'EstacaoCodigo': 'codigoestacao',
                    'Data': 'Data_Hora_Dado'}
        case "QualAguaStatus":
            return {'QualAguaID': 'Registro_ID'}
        case "PerfilTransversal":
            return {'RegistroID': 'Registro_ID'}

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

import json
from datetime import datetime
from typing import List

from sqlalchemy import select

from hidrocli.models.hidro import (
    HidroBase, State, Station, VerticalCrossSection, WaterQuality,
)

HIDRO_DB = None

from hidrocli.database import get_hidro_model, get_verify_keys, get_station_period

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%H:%M:%S")


def coerce_value(value):
    """Best-effort JSON/date coercion for a raw ANA value."""

    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            for fmt in _DATE_FORMATS:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
    return value


def _station_type(value):
    match value:
        case "Fluviometrica":
            return 1
        case "Pluviometrica":
            return 2
        case _:
            raise ValueError(f"Unknown station type: {value}")


def _ana_fields(model):
    """Return ``(attribute, ana_key)`` for every column that declares one."""

    return [
        (column.key, column.info["ana"])
        for column in model.__table__.columns
        if "ana" in column.info
    ]


def normalize_items(job_name, items):
    """Rename ANA keys to model attributes and coerce types in one pass."""

    if isinstance(items, dict):
        items = [items]

    model  = get_hidro_model(job_name)
    fields = _ana_fields(model)

    if job_name == "QualAgua":
        fields += [
            (attr, key)
            for attr, key in _ana_fields(get_hidro_model("QualAguaStatus"))
            if key != "QualAguaID"
        ]
    if job_name == "PerfilTransversal":
        fields += [("Cota", "Cota"), ("Distancia", "Distancia")]

    normalized = []
    for item in items:
        row = {
            key: value for key, value in item.items()
            if str(key).startswith("_")
        }
        row.update({
            attr: coerce_value(item[key])
            for attr, key in fields
            if key is not None and key in item
        })
        if job_name == "Estacao":
            row["TipoEstacao"] = _station_type(item.get("Tipo_Estacao"))
        normalized.append(row)
    return normalized


def insert_hidro(collection: List[HidroBase], expire = True) -> List[HidroBase]:
    """ Insert a list of Hidro ORM Model into Hidro Database"""

    hidro_session = HIDRO_DB.get_session()
    hidro_session.expire_on_commit = expire
    hidro_session.add_all(collection)
    hidro_session.flush()
    hidro_session.commit()
    hidro_session.close()
    return collection


def make_vertical_cross_section(item: dict, parent_id: int):
    """Build a vertical cross-section row linked to its parent section."""

    return VerticalCrossSection.from_json(item, parent_id)


def get_states() -> State:
    """ Returns registered States in Hidro Database. """

    hidro_session = HIDRO_DB.get_session()
    states = hidro_session.query(State).filter(State.CodigoIBGE.isnot(None)).all()
    hidro_session.close()
    return states


def get_period(model_name: str, only_code=False, with_null_end_date=False):
    """ Returns stations with initial and final periods for an given table in Hidro Database. """

    statement = _create_period_statement(model_name, only_code, with_null_end_date)
    hidro_session = HIDRO_DB.get_session()
    period_data = hidro_session.execute(statement)
    hidro_session.close()
    return period_data


def _create_period_statement(model_name, only_code: bool, with_null_end_date: bool):
    columns = [Station.Codigo]
    start_col, end_col = (
        getattr(Station, attr) for attr in get_station_period(model_name)
    )
    if not only_code:
        columns.extend([start_col, end_col])
    statement = select(*columns).where(start_col.isnot(None))
    if with_null_end_date:
        statement = statement.where(end_col.is_(None))
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

    # SQLite allows 32,766 bound parameters per statement. Keep the key
    # lookup below that, and cap the update mapping by column count so wide
    # models such as QualAgua do not build oversized batches.
    select_chunk  = max(1, 20_000 // max(1, len(verify_keys)))
    mapping_chunk = max(1, 200_000 // max(1, len(model.__table__.columns)))
    chunk_size    = min(select_chunk, mapping_chunk)

    key_columns   = [getattr(model, key) for key in verify_keys]
    new_entries   = []
    processed     = set()

    try:
        for start in range(0, len(items), chunk_size):
            chunk = items[start:start + chunk_size]

            filters = [
                getattr(model, attr).in_(
                    [item.get(attr) for item in chunk]
                )
                for attr in verify_keys
            ]
            rows = (
                hidro_session.query(model.RegistroID, *key_columns)
                .filter(*filters)
                .all()
            )
            existing = {tuple(row[1:]): row[0] for row in rows}

            updates = []
            for item in chunk:
                key = tuple(item.get(attr) for attr in verify_keys)
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


def get_registro_ids(job_name: str, items):
    """Return the local ``RegistroID`` for items already written to Hidro DB.

    The result follows the order of ``items`` and contains ``None`` for rows
    that could not be matched.
    """

    if not items:
        return []

    model       = get_hidro_model(job_name)
    verify_keys = get_verify_keys(job_name)
    key_names   = list(verify_keys)
    key_columns = [getattr(model, key) for key in verify_keys]

    select_chunk = max(1, 20_000 // max(1, len(key_names)))
    found        = {}

    hidro_session = HIDRO_DB.get_session()
    try:
        for start in range(0, len(items), select_chunk):
            chunk   = items[start:start + select_chunk]
            filters = [
                getattr(model, attr).in_(
                    [item.get(attr) for item in chunk]
                )
                for attr in verify_keys
            ]
            rows = (
                hidro_session.query(model.RegistroID, *key_columns)
                .filter(*filters)
                .all()
            )
            found.update({tuple(row[1:]): row[0] for row in rows})
    finally:
        hidro_session.close()

    return [
        found.get(tuple(item.get(attr) for attr in key_names))
        for item in items
    ]


def get_qual_agua_ids(items):
    """Return existing QualAgua ``(station, date) -> RegistroID`` mappings."""

    if not items:
        return {}

    codes = list({item["EstacaoCodigo"] for item in items})
    dates = list({item["Data"] for item in items})

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


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

"""Round-trip tests against real committed ANA payloads.

Each base and series job has a small representative payload under
``tests/json/`` (trimmed from a live ANA download). These tests run the
payload through the same convert -> validate -> write path used by
``hidrocli.jobs``, so a broken ``from_json`` mapping or verify key fails
without needing the full download cache.
"""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hidrocli.config import setup_logger
from hidrocli.database import DatabaseType, _setup_db
from hidrocli.database.hidro import (
    count_hidro, get_hidro_model, get_verify_keys,
)
from hidrocli.jobs import (
    JobConfig, convert_json_items,
    validate_series_items, validate_series_items_date,
    write_data,
)
from hidrocli.models.hidro import HidroBase

setup_logger()

ALL_JOBS = list(JobConfig.Base) + list(JobConfig.Series)
FIXTURES = Path(__file__).parent / "json"


@pytest.fixture
def hidro_db(tmp_path):
    connection = _setup_db(str(tmp_path / "hidro.db"), DatabaseType.HIDRO)
    with patch("hidrocli.database.hidro.HIDRO_DB", connection):
        yield connection
        HidroBase.metadata.drop_all(connection.engine)
        connection.close()


def load_fixture(name):
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    return data if isinstance(data, list) else [data]


def fake_job():
    return SimpleNamespace(
        ID=0,
        Status=None,
        Retries=0,
        FromDate=datetime.min,
        ToDate=datetime.max,
    )


def run_transform(name, items):
    items = convert_json_items(name, items)
    if isinstance(name, JobConfig.Series):
        job = fake_job()
        items = validate_series_items(job, name, items)
        items = validate_series_items_date(job, name, items)
    return items


def _normalize(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


@pytest.mark.parametrize("name", ALL_JOBS)
def test_roundtrip_loads_rows(name, hidro_db):
    """Each job's real payload survives convert -> validate -> write."""

    items = run_transform(name, load_fixture(name))
    write_data(name, [], items)

    assert count_hidro(get_hidro_model(name)) > 0


@pytest.mark.parametrize("name", ALL_JOBS)
def test_verify_keys_match_from_json(name):
    """The verify-key JSON field agrees with the model's from_json mapping."""

    item = convert_json_items(name, load_fixture(name))[0]
    model = get_hidro_model(name)
    row = model.from_json(item)

    for model_attr, json_key in get_verify_keys(name).items():
        assert json_key in item, f"{name}: {json_key!r} missing from payload"
        assert _normalize(getattr(row, model_attr)) == _normalize(item[json_key]), (
            f"{name}: {model_attr} maps to {getattr(row, model_attr)!r} "
            f"but payload {json_key!r} is {item[json_key]!r}"
        )

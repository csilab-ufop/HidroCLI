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

"""
HidroCLI job registry: the single source of job-level metadata.

Each entry describes the job kind, how repeated payload items are collapsed
(``dedup``), the date field used to filter a window, and the series validation
spec. The ORM side (model, job-queue model, upsert identity, station period) is
provided by ``hidrocli.database``; ``jobs`` only receives it.
"""

from enum import StrEnum, auto
from typing import NamedTuple

from hidrocli.database import (
    SeriesTables, TelemetryTables, get_field_names, get_verify_keys,
)

_QUALAGUA_NON_PARAM_ATTRS = {
    "Choveu", "Data", "NivelConsistencia", "NumMedicao", "PosHorizColeta",
    "PosVertColeta", "Profundidade", "EstacaoCodigo", "DataAlt",
}


class DedupMode(StrEnum):
    """Strategy used to compute a deduplication key."""

    TUPLE  = auto()
    """hash the values of ``keys``, coercing any named in ``stringify`` to ``str`` first."""

    WHOLE  = auto()
    """hash the entire item (ignoring private ``_`` keys)."""

    SINGLE = auto()
    """hash ``keys[0]``, skipping items where it is missing."""


class Dedup(NamedTuple):
    """How repeated payload items are collapsed before writing."""

    mode:      DedupMode
    keys:      tuple = ()
    stringify: tuple = ()


JOB_OVERRIDES = {
    "ResumoDescarga": {"dedup": Dedup(DedupMode.WHOLE)},
    "CurvaDescarga": {
        "dedup": Dedup(
            DedupMode.TUPLE,
            ("EstacaoCodigo", "NumeroCurva", "PeriodoValidadeInicio", "PeriodoValidadeFim"),
            ("NumeroCurva",),
        ),
    },
    "QualAgua": {
        "exclude_attrs": _QUALAGUA_NON_PARAM_ATTRS,
        "extra_expected": "status",
    },
    "PerfilTransversal": {
        "dedup": Dedup(DedupMode.SINGLE, ("ANA_RegistroID",)),
        "optional_keys": ["ANA_RegistroID"],
        "exclude_attrs": {"DataAlt", "ANA_RegistroID"},
    },
    "Telemetria": {
        "exclude_attrs": {"DataAlt"},
    },
}


def _spec(name: str) -> dict:
    return JOB_OVERRIDES.get(name, {})


def get_date_key(name: str):
    """Return the date attribute for a job (``None`` when it has no date)."""
    return "Data" if "Data" in get_field_names(name) else None


def get_dedup(name: str):
    """Return the deduplication spec for a series job."""
    override = _spec(name).get("dedup")
    if override is not None:
        return override
    return Dedup(DedupMode.TUPLE, tuple(get_verify_keys(name)))


def expected_keys(name: str):
    """Return ``(optional_keys, expected_keys)`` for a series job."""
    entry = _spec(name)
    exclude = entry.get("exclude_attrs", ())
    keys = [attr for attr in get_field_names(name) if attr not in exclude]
    if entry.get("extra_expected") == "status":
        keys += [f"QualAgua{i:03d}Status" for i in range(1, 148)]
    return entry.get("optional_keys", []), keys


def series_job_names():
    """Return the series job names."""
    return [table.value for table in SeriesTables]


def selectable_job_names():
    """Return every job name accepted by ``--skip-for`` / ``--run-for``."""
    return series_job_names() + [table.value for table in TelemetryTables]

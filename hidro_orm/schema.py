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

"""Schema metadata and Alembic compatibility filters.

Deployed databases may contain unmanaged tables that are not part of the
current ORM metadata.  Reflected objects outside the managed metadata are
ignored so a legacy database can be adopted without dropping unrelated data.
"""

from enum import StrEnum
from pathlib import Path

from sqlalchemy import MetaData

BASELINE_REVISION = "v0.0.0"

LEGACY_OBJECT_NAMES = frozenset({"uq_series_jobs"})
"""Legacy constraint/index names that must not be dropped by autogenerate."""


class DbKind(StrEnum):
    """Supported database migration chains."""

    HIDRO = "hidro"
    CLIENT = "client"


def metadata_for(kind: DbKind | str) -> MetaData:
    """Return the ORM metadata for ``kind``."""

    kind = DbKind(kind)
    if kind is DbKind.HIDRO:
        from hidrocli.models.hidro import HidroBase

        return HidroBase.metadata

    from hidrocli.models.client import ClientBase

    return ClientBase.metadata


def sqlite_url(db_path: str | Path) -> str:
    """Build an absolute SQLite URL for ``db_path``."""

    path = Path(db_path).expanduser().resolve()
    return f"sqlite:///{path}"


def make_include_object(metadata: MetaData):
    """Build a filter that ignores reflected objects outside ``metadata``."""

    managed_tables = set(metadata.tables)

    def include_object(object_, name, type_, reflected, compare_to) -> bool:
        if reflected and type_ == "table" and name not in managed_tables:
            return False

        table = getattr(object_, "table", None)
        if reflected and table is not None and table.name not in managed_tables:
            return False

        if name in LEGACY_OBJECT_NAMES:
            return False

        return True

    return include_object

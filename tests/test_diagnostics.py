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

import logging

from hidrocli.database import DatabaseConnection, DatabaseType
from hidrocli.database import diagnostics
from hidro_orm import runner
from hidro_orm.schema import DbKind


def _database(tmp_path):
    path = str(tmp_path / "hidro.db")
    runner.upgrade(DbKind.HIDRO, path)
    return path, DatabaseConnection(path, DatabaseType.HIDRO)


def _messages(caplog):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "hidrocli.database.diagnostics"
    ]


def test_diagnostics_are_silent_at_info(tmp_path, caplog):
    path, database = _database(tmp_path)
    try:
        caplog.set_level(logging.INFO, logger="hidrocli.database.diagnostics")
        diagnostics.log_database_diagnostics(DbKind.HIDRO, path, database)
        assert _messages(caplog) == []
    finally:
        database.close()


def test_diagnostics_cheap_checks_at_trace(tmp_path, caplog):
    path, database = _database(tmp_path)
    try:
        caplog.set_level(diagnostics.TRACE, logger="hidrocli.database.diagnostics")
        diagnostics.log_database_diagnostics(DbKind.HIDRO, path, database)
        messages = _messages(caplog)
        assert any("foreign_keys=" in message for message in messages)
        assert any("schema matches metadata" in message for message in messages)
        assert not any("quick_check" in message for message in messages)
    finally:
        database.close()


def test_diagnostics_deep_checks_at_debug(tmp_path, caplog):
    path, database = _database(tmp_path)
    try:
        caplog.set_level(logging.DEBUG, logger="hidrocli.database.diagnostics")
        diagnostics.log_database_diagnostics(DbKind.HIDRO, path, database)
        messages = _messages(caplog)
        assert any("quick_check=ok" in message for message in messages)
        assert not any("integrity_check" in message for message in messages)
    finally:
        database.close()


def test_diagnostics_full_checks_at_verbose(tmp_path, caplog):
    path, database = _database(tmp_path)
    try:
        caplog.set_level(diagnostics.VERBOSE, logger="hidrocli.database.diagnostics")
        diagnostics.log_database_diagnostics(DbKind.HIDRO, path, database)
        messages = _messages(caplog)
        assert any("integrity_check=ok" in message for message in messages)
    finally:
        database.close()


def test_database_error_hook_logs_without_parameters(tmp_path, caplog):
    _, database = _database(tmp_path)
    try:
        caplog.set_level(logging.WARNING, logger="hidrocli.database.diagnostics")
        try:
            with database.engine.connect() as connection:
                connection.exec_driver_sql(
                    "SELECT * FROM missing_table WHERE value = ?", (123,)
                )
        except Exception:
            pass
        messages = _messages(caplog)
        assert any("missing_table" in message for message in messages)
        assert all("123" not in message for message in messages)
    finally:
        database.close()

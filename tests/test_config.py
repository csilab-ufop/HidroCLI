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

import hidrocli.config

def test_setup_arguments_defaults():
    """Test default argument values"""

    with patch('sys.argv', ['script_name']):
        import hidrocli.jobs.runner
        hidrocli.config.setup_arguments()
        assert hidrocli.config.LOG_LEVEL   == 'INFO'
        assert hidrocli.config.CLIENT_PATH == 'db/client.db'
        assert hidrocli.config.HIDRO_PATH  == 'db/hidro.db'
        assert hidrocli.jobs.runner.MAX_WORKERS   == 10
        assert hidrocli.jobs.runner.BATCH_SIZE    == 1000
        assert hidrocli.jobs.runner.FILTER        == 'DATA_ULTIMA_ATUALIZACAO'
        assert hidrocli.jobs.runner.STATIONS      == []
        assert hidrocli.jobs.runner.INITIAL_DATE  is None
        assert hidrocli.jobs.runner.FINAL_DATE    is None
        assert hidrocli.jobs.runner.SAVE_JSON     is False
        assert hidrocli.jobs.runner.READ_JSON     is False
        assert hidrocli.jobs.runner.JSON_DIR      == 'json'


def test_setup_arguments_custum():
    """Test default argument values"""

    test_arguments = ['script_name',
                      '--log-level',   'DEBUG',
                      '--max-workers', '5',
                      '--batch-size',  '500',
                      '--hidro',       'custom/hidro.db',
                      '--client',      'custom/client.db']

    with patch('sys.argv', test_arguments):
        import hidrocli.jobs.runner, hidrocli.database

        hidrocli.config.setup_arguments()
        assert hidrocli.config.LOG_LEVEL   == 'DEBUG'
        assert hidrocli.config.CLIENT_PATH == 'custom/client.db'
        assert hidrocli.config.HIDRO_PATH  == 'custom/hidro.db'
        assert hidrocli.jobs.runner.MAX_WORKERS   == 5
        assert hidrocli.jobs.runner.BATCH_SIZE    == 500


def test_setup_arguments_filter_and_integer_stations():
    test_arguments = ['script_name',
                      '--stations', '111', '222',
                      '--filter',   'DATA_LEITURA']

    with patch('sys.argv', test_arguments):
        import hidrocli.jobs.runner

        hidrocli.config.setup_arguments()

        assert hidrocli.jobs.runner.STATIONS == [111, 222]
        assert hidrocli.jobs.runner.FILTER   == 'DATA_LEITURA'


def test_setup_arguments_save_json_flags():
    test_arguments = ['script_name',
                      '--save-json',
                      '--json-dir', 'custom/json']

    with patch('sys.argv', test_arguments):
        import hidrocli.jobs.runner

        hidrocli.config.setup_arguments()

        assert hidrocli.jobs.runner.SAVE_JSON is True
        assert hidrocli.jobs.runner.JSON_DIR  == 'custom/json'


def test_setup_arguments_read_json_flag():
    test_arguments = ['script_name',
                      '--read-json',
                      '--json-dir', 'custom/json']

    with patch('sys.argv', test_arguments):
        import hidrocli.jobs.runner

        hidrocli.config.setup_arguments()

        assert hidrocli.jobs.runner.READ_JSON is True
        assert hidrocli.jobs.runner.JSON_DIR  == 'custom/json'


def test_setup_arguments_accepts_none_log_level():
    with patch('sys.argv', ['script_name', '--log-level', 'NONE']):
        hidrocli.config.setup_arguments()

    assert hidrocli.config.LOG_LEVEL == 'NONE'


def test_setup_logger_none_disables_logging():
    import logging
    hidrocli.config.LOG_LEVEL = 'NONE'

    with patch('logging.basicConfig') as mock_config:
        hidrocli.config.setup_logger()

    assert mock_config.call_args.kwargs['level'] == logging.CRITICAL + 1


def _log_formatter_record(message, level=None):
    import logging
    level = level or logging.INFO
    return logging.LogRecord('test', level, __file__, 1, message, (), None)


def test_log_formatter_moves_tag_into_prefix():
    formatter = hidrocli.config._LogFormatter()
    record = _log_formatter_record(
        "[WRITER Chuvas]: Total processed Data: 100, Total finished Jobs: 1000"
    )

    formatted = formatter.format(record)

    assert formatted.startswith("[INFO ")
    assert " - WRITER Chuvas]: Total processed Data: 100" in formatted
    assert "1000" in formatted


def test_log_formatter_keeps_untagged_message():
    formatter = hidrocli.config._LogFormatter()
    record = _log_formatter_record("plain message")

    formatted = formatter.format(record)

    assert formatted.endswith("]: plain message")
    assert " - " not in formatted


def test_setup_logger_creates_custom_levels(caplog):

    import logging;
    VERBOSE = 5
    hidrocli.config.LOG_LEVEL = VERBOSE
    hidrocli.config.setup_logger()
    caplog.set_level(VERBOSE)

    logging.getLogger().trace("trace message")
    assert "trace message" in caplog.text
    assert "TRACE" in caplog.text

    logging.getLogger().verbose("verbose message")
    assert "verbose message" in caplog.text
    assert "VERBOSE" in caplog.text


def test_setup_arguments_parses_initial_and_final_dates(monkeypatch):
    from datetime import datetime
    import hidrocli.jobs.runner

    monkeypatch.setattr(hidrocli.jobs.runner, "INITIAL_DATE", None)
    monkeypatch.setattr(hidrocli.jobs.runner, "FINAL_DATE", None)

    test_arguments = ['script_name',
                      '--initial-date', '2020-01-01',
                      '--final-date',   '2020-12-31']

    with patch('sys.argv', test_arguments):
        hidrocli.config.setup_arguments()

    assert hidrocli.jobs.runner.INITIAL_DATE == datetime(2020, 1, 1)
    assert hidrocli.jobs.runner.FINAL_DATE   == datetime(2020, 12, 31)


def test_setup_arguments_rejects_invalid_date_format():
    with patch('sys.argv', ['script_name', '--initial-date', '01/02/2020']):
        with pytest.raises(SystemExit):
            hidrocli.config.setup_arguments()


def test_setup_arguments_rejects_inverted_date_range():
    test_arguments = ['script_name',
                      '--initial-date', '2021-01-01',
                      '--final-date',   '2020-01-01']

    with patch('sys.argv', test_arguments):
        with pytest.raises(SystemExit):
            hidrocli.config.setup_arguments()

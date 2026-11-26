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
from datetime import datetime
from unittest.mock import patch

import pytest

import hidrocli.config
from hidrocli.config import Config, parse_config, setup_logger


def test_parse_config_defaults():
    cfg = parse_config([])
    assert cfg.LOG_LEVEL    == 'INFO'
    assert cfg.CLIENT_PATH  == 'db/client.db'
    assert cfg.HIDRO_PATH   == 'db/hidro.db'
    assert cfg.MAX_WORKERS  == 10
    assert cfg.BATCH_SIZE   == 1000
    assert cfg.FILTER       == 'DATA_ULTIMA_ATUALIZACAO'
    assert cfg.STATIONS     == ()
    assert cfg.SKIP_FOR     == ()
    assert cfg.RUN_FOR      == ()
    assert cfg.INITIAL_DATE is None
    assert cfg.FINAL_DATE   is None
    assert cfg.SAVE_JSON    is False
    assert cfg.READ_JSON    is False
    assert cfg.JSON_DIR     == 'json'
    assert cfg.TRACE_RECORDS is False


def test_parse_config_custom():
    cfg = parse_config([
        '--log-level',   'DEBUG',
        '--max-workers', '5',
        '--batch-size',  '500',
        '--hidro',       'custom/hidro.db',
        '--client',      'custom/client.db',
    ])
    assert cfg.LOG_LEVEL   == 'DEBUG'
    assert cfg.CLIENT_PATH == 'custom/client.db'
    assert cfg.HIDRO_PATH  == 'custom/hidro.db'
    assert cfg.MAX_WORKERS == 5
    assert cfg.BATCH_SIZE  == 500


def test_parse_config_filter_and_stations():
    cfg = parse_config(['--stations', '111', '222', '--filter', 'DATA_LEITURA'])
    assert cfg.STATIONS == (111, 222)
    assert cfg.FILTER   == 'DATA_LEITURA'


def test_parse_config_save_json_flags():
    cfg = parse_config(['--save-json', '--json-dir', 'custom/json'])
    assert cfg.SAVE_JSON is True
    assert cfg.JSON_DIR  == 'custom/json'


def test_parse_config_read_json_flag():
    cfg = parse_config(['--read-json', '--json-dir', 'custom/json'])
    assert cfg.READ_JSON is True
    assert cfg.JSON_DIR  == 'custom/json'


def test_parse_config_trace_records_flag():
    cfg = parse_config(['--trace-records'])
    assert cfg.TRACE_RECORDS is True


def test_parse_config_selection_includes_telemetry():
    cfg = parse_config(['--run-for', 'Telemetria', 'Chuvas'])
    assert cfg.RUN_FOR == ('Telemetria', 'Chuvas')

    cfg = parse_config(['--skip-for', 'Telemetria'])
    assert cfg.SKIP_FOR == ('Telemetria',)


def test_parse_config_accepts_none_log_level():
    cfg = parse_config(['--log-level', 'NONE'])
    assert cfg.LOG_LEVEL == 'NONE'


def test_parse_config_parses_initial_and_final_dates():
    cfg = parse_config([
        '--initial-date', '2020-01-01',
        '--final-date',   '2020-12-31',
    ])
    assert cfg.INITIAL_DATE == datetime(2020, 1, 1)
    assert cfg.FINAL_DATE   == datetime(2020, 12, 31)


def test_parse_config_rejects_invalid_date_format():
    with pytest.raises(SystemExit):
        parse_config(['--initial-date', '01/02/2020'])


def test_parse_config_rejects_inverted_date_range():
    with pytest.raises(SystemExit):
        parse_config([
            '--initial-date', '2021-01-01',
            '--final-date',   '2020-01-01',
        ])


def test_setup_logger_none_disables_logging():
    with patch('logging.basicConfig') as mock_config:
        setup_logger(Config(LOG_LEVEL='NONE'))

    assert mock_config.call_args.kwargs['level'] == logging.CRITICAL + 1


def test_setup_logger_creates_custom_levels(caplog):
    VERBOSE = 5
    setup_logger(Config(LOG_LEVEL=VERBOSE))
    caplog.set_level(VERBOSE)

    logging.getLogger().trace("trace message")
    assert "trace message" in caplog.text
    assert "TRACE" in caplog.text

    logging.getLogger().verbose("verbose message")
    assert "verbose message" in caplog.text
    assert "VERBOSE" in caplog.text


def _log_formatter_record(message, level=None):
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

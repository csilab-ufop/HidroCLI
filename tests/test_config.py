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
        import hidrocli.jobs
        hidrocli.config.setup_arguments()
        assert hidrocli.config.LOG_LEVEL   == 'INFO'
        assert hidrocli.config.CLIENT_PATH == 'db/client.db'
        assert hidrocli.config.HIDRO_PATH  == 'db/hidro.db'
        assert hidrocli.jobs.MAX_WORKERS   == 10
        assert hidrocli.jobs.BATCH_SIZE    == 1000
        assert hidrocli.jobs.FILTER        == 'DATA_ULTIMA_ATUALIZACAO'
        assert hidrocli.jobs.STATIONS      == []
        assert hidrocli.jobs.SAVE_JSON     is False
        assert hidrocli.jobs.READ_JSON     is False
        assert hidrocli.jobs.JSON_DIR      == 'json'


def test_setup_arguments_custum():
    """Test default argument values"""

    test_arguments = ['script_name',
                      '--log-level',   'DEBUG',
                      '--max-workers', '5',
                      '--batch-size',  '500',
                      '--hidro',       'custom/hidro.db',
                      '--client',      'custom/client.db']

    with patch('sys.argv', test_arguments):
        import hidrocli.jobs, hidrocli.database

        hidrocli.config.setup_arguments()
        assert hidrocli.config.LOG_LEVEL   == 'DEBUG'
        assert hidrocli.config.CLIENT_PATH == 'custom/client.db'
        assert hidrocli.config.HIDRO_PATH  == 'custom/hidro.db'
        assert hidrocli.jobs.MAX_WORKERS   == 5
        assert hidrocli.jobs.BATCH_SIZE    == 500


def test_setup_arguments_filter_and_integer_stations():
    test_arguments = ['script_name',
                      '--stations', '111', '222',
                      '--filter',   'DATA_LEITURA']

    with patch('sys.argv', test_arguments):
        import hidrocli.jobs

        hidrocli.config.setup_arguments()

        assert hidrocli.jobs.STATIONS == [111, 222]
        assert hidrocli.jobs.FILTER   == 'DATA_LEITURA'


def test_setup_arguments_save_json_flags():
    test_arguments = ['script_name',
                      '--save-json',
                      '--json-dir', 'custom/json']

    with patch('sys.argv', test_arguments):
        import hidrocli.jobs

        hidrocli.config.setup_arguments()

        assert hidrocli.jobs.SAVE_JSON is True
        assert hidrocli.jobs.JSON_DIR  == 'custom/json'


def test_setup_arguments_read_json_flag():
    test_arguments = ['script_name',
                      '--read-json',
                      '--json-dir', 'custom/json']

    with patch('sys.argv', test_arguments):
        import hidrocli.jobs

        hidrocli.config.setup_arguments()

        assert hidrocli.jobs.READ_JSON is True
        assert hidrocli.jobs.JSON_DIR  == 'custom/json'


def test_setup_arguments_accepts_none_log_level():
    with patch('sys.argv', ['script_name', '--log-level', 'NONE']):
        hidrocli.config.setup_arguments()

    assert hidrocli.config.LOG_LEVEL == 'NONE'


def test_setup_logger_none_disables_logging():
    import logging
    hidrocli.config.LOG_LEVEL = 'NONE'

    with patch('logging.basicConfig') as mock_config:
        hidrocli.config.setup_logger()

    mock_config.assert_called_once_with(
        level=logging.CRITICAL + 1,
        format='[%(levelname)s]: %(message)s'
    )


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

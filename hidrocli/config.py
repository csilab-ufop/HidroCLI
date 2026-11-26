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
Provides general config to HidroCLI application.
"""

import logging
import re

from datetime import datetime
from typing import NamedTuple, Optional

from tqdm import tqdm


class Config(NamedTuple):
    """Frozen run configuration built once from command-line arguments.

    Holds the user-facing settings that would otherwise live as mutable module
    globals. ``BULK_SIZE`` stays a plain module constant in
    ``hidrocli.jobs.runner``: it is a tuning knob, not a CLI flag.
    """

    LOG_LEVEL:   str  = "INFO"
    HIDRO_PATH:  str  = "db/hidro.db"
    CLIENT_PATH: str  = "db/client.db"
    MAX_WORKERS: int  = 10
    BATCH_SIZE:  int  = 1000
    SKIP_SERIES_JOBS: bool = False
    SKIP_FOR:  tuple = ()
    RUN_FOR:   tuple = ()
    STATIONS:  tuple = ()
    FILTER:    str   = "DATA_ULTIMA_ATUALIZACAO"
    INITIAL_DATE: Optional[datetime] = None
    FINAL_DATE:   Optional[datetime] = None
    SAVE_JSON:    bool = False
    READ_JSON:    bool = False
    JSON_DIR:     str  = "json"
    TRACE_RECORDS: bool = False


_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _parse_date(value):
    """Parse a command-line date in the ``yyyy-mm-dd`` format."""

    import argparse

    try:
        if not _DATE_RE.fullmatch(value):
            raise ValueError
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid date '{value}', expected format yyyy-mm-dd"
        ) from None


def parse_config(argv=None):
    """Parse command-line arguments into a frozen :class:`Config`."""

    import argparse
    parser = argparse.ArgumentParser(prog='hidrocli')

    parser.add_argument('--hidro', type=str, default='db/hidro.db',
                        help='Path to Hidro Database file')

    parser.add_argument('--client', type=str, default='db/client.db',
                        help='Path to Client Database file')

    parser.add_argument('--max-workers', type=int, default=10, help='Maximum number of worker threads')

    parser.add_argument('--batch-size',  type=int, default=1000,
                        help='Batch size threshold to write job data on Hidro Database')

    parser.add_argument('--log-level', default='INFO',
                        choices=['TRACE', 'VERBOSE', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'NONE'],
                        help='Set logging level (NONE disables all logging)')

    parser.add_argument('--skip-series-jobs', action='store_true', default=False,
                        help='Skip all series and telemetry jobs when present')

    from hidrocli.jobs import selectable_job_names

    parser.add_argument('--skip-for', default=[], nargs='*',
                        choices=selectable_job_names(),
                        help='Skip job creation and requesition for the given choices')

    parser.add_argument('--run-for', default=[], nargs='*',
                        choices=selectable_job_names(),
                        help='Runs only the choosen Jobs')

    parser.add_argument('--stations', default=[], nargs='*', type=int,
                        help='Station codes to filter series and telemetry jobs')

    from hidrocli.models.client import FILTERS

    parser.add_argument('--filter', default='DATA_ULTIMA_ATUALIZACAO',
                        choices=FILTERS,
                        help='Date filter sent to the API (default: DATA_ULTIMA_ATUALIZACAO)')

    parser.add_argument('--initial-date', type=_parse_date, default=None,
                        metavar='YYYY-MM-DD',
                        help='Initial date for series and telemetry jobs; defaults to each station period start')

    parser.add_argument('--final-date', type=_parse_date, default=None,
                        metavar='YYYY-MM-DD',
                        help='Final date for series and telemetry jobs; defaults to each station period end')

    parser.add_argument('--save-json', action='store_true', default=False,
                        help='Save raw JSON payloads retrieved from the API')

    parser.add_argument('--read-json', action='store_true', default=False,
                        help='Read raw JSON payloads from the JSON directory before requesting the API')

    parser.add_argument('--json-dir', type=str, default='json',
                        help='Directory where raw JSON payloads are read from and saved')

    parser.add_argument('--trace-records', action='store_true', default=False,
                        help='Save JobRecords provenance for written data rows')

    args = parser.parse_args(argv)

    if (args.initial_date is not None and args.final_date is not None and
            args.initial_date > args.final_date):
        parser.error('--initial-date must be on or before --final-date')

    return Config(
        LOG_LEVEL    = args.log_level,
        HIDRO_PATH   = args.hidro,
        CLIENT_PATH  = args.client,
        MAX_WORKERS  = args.max_workers,
        BATCH_SIZE   = args.batch_size,
        SKIP_SERIES_JOBS = args.skip_series_jobs,
        SKIP_FOR     = tuple(args.skip_for),
        RUN_FOR      = tuple(args.run_for),
        STATIONS     = tuple(args.stations),
        FILTER       = args.filter,
        INITIAL_DATE = args.initial_date,
        FINAL_DATE   = args.final_date,
        SAVE_JSON    = args.save_json,
        READ_JSON    = args.read_json,
        JSON_DIR     = args.json_dir,
        TRACE_RECORDS = args.trace_records,
    )


def setup_logger(config: Config = Config()):
    """ Setup logger object accross application. """

    TRACE = 15
    setattr(logging.Logger, 'trace', _make_logger(TRACE))
    logging.addLevelName(TRACE, 'TRACE')
    VERBOSE = 5
    setattr(logging.Logger, 'verbose', _make_logger(VERBOSE))
    logging.addLevelName(VERBOSE, 'VERBOSE')
    handler = _TqdmLoggingHandler()
    handler.setFormatter(_LogFormatter())
    level = logging.CRITICAL + 1 if config.LOG_LEVEL == 'NONE' else config.LOG_LEVEL
    logging.basicConfig(
        level=level,
        handlers=[handler]
    )


class _TqdmLoggingHandler(logging.StreamHandler):
    """Write log lines through ``tqdm`` so they do not overwrite a live bar.

    Both the handler and the progress bar target stderr, so the bar is cleared,
    the line is written, and the bar is redrawn underneath.
    """

    def emit(self, record):
        try:
            tqdm.write(self.format(record), file=self.stream)
        except Exception:
            self.handleError(record)


class _LogFormatter(logging.Formatter):
    """Fold a leading ``[TAG]`` from the message into the level prefix.

    ``[WRITER Chuvas]: Total processed`` becomes
    ``[INFO 2026-11-20 21:28:21 - WRITER Chuvas]: Total processed``.
    Messages without a leading tag keep the plain prefix.
    """

    def __init__(self):
        super().__init__(
            fmt='[%(levelname)s %(asctime)s%(tag)s]: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            defaults={'tag': ''}
        )

    def format(self, record):
        message = record.getMessage()
        match   = re.match(r'\[([^\]]+)\]:?\s(.*)', message, re.DOTALL)
        if match:
            record      = logging.makeLogRecord(record.__dict__)
            record.tag  = f" - {match.group(1)}"
            record.msg  = match.group(2)
            record.args = ()
        return super().format(record)


def _make_logger(level):
    """ Helper method to create TRACE and VERBOSE logger modes. """

    def logger(self, msg, *args, **kwargs):
        if self.isEnabledFor(level):
            self._log(level, msg, args, **kwargs)
    return logger


def setup_database(config: Config):
    """ Setup Hidro and Client Database. """

    import hidrocli.database        as db
    import hidrocli.database.client as client
    db.init_db(config.HIDRO_PATH, config.CLIENT_PATH)
    if not client.check_credentials():
        user_id = input("Enter API username: ")
        import getpass;
        password = getpass.getpass("Enter API password: ")
        client.insert_credentials(user_id, password)

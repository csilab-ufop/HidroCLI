# <img src="assets/icon.png" alt="HidroCLI icon" width="64" height="64" align="absmiddle"> HidroCLI

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-BSD--2--Clause-blue)](LICENSE)
[![Documentation](https://img.shields.io/badge/docs-wiki-blue)](https://github.com/csilab-ufop/HidroCLI/wiki)
[![Release](https://github.com/csilab-ufop/hidrocli/actions/workflows/release.yml/badge.svg)](https://github.com/csilab-ufop/hidrocli/actions/workflows/release.yml)

A Python application tool to request and sync data from ANA Hidro WebServices.

## Installation

- Requires Python 3.11+ and [sqlite3](https://sqlite.org/index.html).
- Install directly from the repository:
``` shell
    pip install "git+https://github.com/csilab-ufop/hidrocli"
```

## Development

- Clone the repository including the docs submodule:
``` shell
    git clone --recurse-submodules https://github.com/csilab-ufop/hidrocli
```

- Setup your python enviroment and install dependencies:
``` shell
    pip install -e .
```

- Install the documentation tooling:
``` shell
    pip install -e ./hidrocli_docs
```

- Regenerate the wiki pages from the repository root:
``` shell
    hidro-docs
```

## Usage

```
usage: hidrocli [-h] [--hidro HIDRO] [--client CLIENT]
                [--max-workers MAX_WORKERS] [--batch-size BATCH_SIZE]
                [--log-level {TRACE,VERBOSE,DEBUG,INFO,WARNING,ERROR,NONE}]
                [--skip-series-jobs]
                [--skip-for [{Chuvas,ResumoDescarga,Sedimentos,Vazoes,Granulometria,CurvaDescarga,QualAgua,PerfilTransversal,Cotas} ...]]
                [--run-for [{Chuvas,ResumoDescarga,Sedimentos,Vazoes,Granulometria,CurvaDescarga,QualAgua,PerfilTransversal,Cotas} ...]]
                [--stations [STATIONS ...]]
                [--filter {DATA_LEITURA,DATA_ULTIMA_ATUALIZACAO}]
                [--initial-date YYYY-MM-DD] [--final-date YYYY-MM-DD]
                [--save-json] [--read-json] [--json-dir JSON_DIR]

options:
  -h, --help            show this help message and exit
  --hidro HIDRO         Path to Hidro Database file
  --client CLIENT       Path to Client Database file
  --max-workers MAX_WORKERS
                        Maximum number of worker threads
  --batch-size BATCH_SIZE
                        Batch size threshold to write job data on Hidro
                        Database
  --log-level {TRACE,VERBOSE,DEBUG,INFO,WARNING,ERROR,NONE}
                        Set logging level (NONE disables all logging)
  --skip-series-jobs    Skip all series jobs when present
  --skip-for [{Chuvas,ResumoDescarga,Sedimentos,Vazoes,Granulometria,CurvaDescarga,QualAgua,PerfilTransversal,Cotas} ...]
                        Skip job creation and requesition for the given
                        choices
  --run-for [{Chuvas,ResumoDescarga,Sedimentos,Vazoes,Granulometria,CurvaDescarga,QualAgua,PerfilTransversal,Cotas} ...]
                        Runs only the choosen Jobs
  --stations [STATIONS ...]
                        Station codes to filter series jobs
  --filter {DATA_LEITURA,DATA_ULTIMA_ATUALIZACAO}
                        Date filter sent to the API (default:
                        DATA_ULTIMA_ATUALIZACAO)
  --initial-date YYYY-MM-DD
                        Initial date for series jobs; defaults to each station
                        period start
  --final-date YYYY-MM-DD
                        Final date for series jobs; defaults to each station
                        period end
  --save-json           Save raw JSON payloads retrieved from the API
  --read-json           Read raw JSON payloads from the JSON directory before
                        requesting the API
  --json-dir JSON_DIR   Directory where raw JSON payloads are read from and
                        saved
```

## Documentation

- [HidroCLI Wiki](https://github.com/csilab-ufop/HidroCLI/wiki)

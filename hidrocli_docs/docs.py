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

"""Generate the Hidro documentation wiki pages.

This is the implementation of the ``hidro-docs`` console command.  It runs
``pydoc-markdown``, applies the wiki markdown post-processing, and finally
regenerates the curated Hidro and Client model pages from the ORM models.
"""

from __future__ import annotations

import ast
import html
import importlib.util
import inspect
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

def find_project_root() -> Path:
    """Locate the source checkout, even when installed in site-packages."""
    candidates = [Path.cwd(), Path(__file__).resolve().parent]
    for base in candidates:
        for path in (base, *base.parents):
            if (
                (path / "pyproject.toml").is_file()
                and (path / "hidrocli" / "models" / "hidro.py").is_file()
            ):
                return path
    raise SystemExit(
        "could not locate the HidroCLI source checkout; run hidro-docs "
        "from the repository root"
    )


ROOT = find_project_root()
DOCS_ROOT = ROOT / "hidrocli_docs"
WIKI_DIR = DOCS_ROOT / "wiki"
MODEL_FILE = ROOT / "hidrocli" / "models" / "hidro.py"
CLIENT_MODEL_FILE = ROOT / "hidrocli" / "models" / "client.py"
OUTPUT_FILE = WIKI_DIR / "hidro models.md"
CLIENT_OUTPUT_FILE = WIKI_DIR / "client models.md"

# Friendly titles for the pydoc-markdown module pages (keyed by page name).
MODULE_TITLES = {
    "config": "Config",
    "jobs": "Jobs",
    "webservices": "WebServices",
    "client database": "Client Database",
    "hidro database": "Hidro Database",
}

# Conceptual relationships for the Hidro ER diagram. Relationships are keyed by
# ``EstacaoCodigo``/``RegistroID``, not database-enforced foreign keys.
HIDRO_ER = [
    ("Bacia", "SubBacia", "contains"),
    ("Bacia", "Rio", "contains"),
    ("SubBacia", "Rio", "contains"),
    ("Estado", "Municipio", "contains"),
    ("Municipio", "Estacao", "locates"),
    ("Rio", "Estacao", "on"),
    ("Estacao", "Chuvas", "records"),
    ("Estacao", "Cotas", "records"),
    ("Estacao", "Vazoes", "records"),
    ("Estacao", "ResumoDescarga", "records"),
    ("Estacao", "Sedimentos", "records"),
    ("Estacao", "CurvaDescarga", "records"),
    ("Estacao", "QualAgua", "records"),
    ("Estacao", "Granulometria", "records"),
    ("Estacao", "PerfilTransversal", "records"),
    ("Estacao", "Telemetria", "records"),
    ("QualAgua", "QualAguaStatus", "status flags"),
    ("PerfilTransversal", "PerfilTransversalVert", "verticals"),
]

CLIENT_CONCEPTUAL_ER = [
    ("BaseJobs", "JobRecords", "produces"),
    ("StationJobs", "JobRecords", "produces"),
    ("SeriesJobs", "JobRecords", "produces"),
    ("TelemetryJobs", "JobRecords", "produces"),
]

ARCH_PAGE = """# Application Architecture

HidroCLI is a two-database ETL: it plans work in the client database, fetches ANA
payloads (live or from the `json/` cache), and writes normalized rows to the
Hidro database.

## Runtime flow

```mermaid
flowchart TD
    CLI["CLI<br/>hidrocli/__main__.py"] --> CONFIG["Config<br/>hidrocli/config.py"]
    CONFIG --> SETUP["Database setup<br/>Alembic migrations"]
    SETUP --> JOBS["Job runner<br/>base / series / telemetry"]
    JOBS -->|"token + requests"| ANA["ANA Hidro WebServices<br/>live API or json/ cache"]
    ANA -->|"items"| JOBS
    JOBS -->|"normalize + validate"| QUEUE["Write queue"]
    QUEUE --> WRITER["Single writer thread<br/>db_writer"]
    WRITER --> HIDRO[("Hidro DB")]
    WRITER --> CLIENT[("Client DB")]
```

The client database also stores credentials, cached tokens, the persistent job
queues, and `JobRecords` provenance. The Hidro database stores the normalized
reference and time-series data.

## Job lifecycle

```mermaid
stateDiagram-v2
    [*] --> PENDING
    [*] --> CORRUPTED: invalid planning dates
    PENDING --> COMPLETED: rows written
    PENDING --> EMPTY: success, no items
    PENDING --> FAILED: validation or request error
    PENDING --> INVALID: 417 SQLGrammarException
    PENDING --> PENDING: timeout / 429 / 5xx / auth
    FAILED --> PENDING: retry
    COMPLETED --> PENDING: stale series window
    EMPTY --> PENDING: stale series window
    COMPLETED --> [*]
    EMPTY --> [*]
    INVALID --> [*]
    CORRUPTED --> [*]
```

`FAILED` jobs are retried on later runs while `Retries` is below the limit.
`EMPTY` means the API succeeded but returned no items. `INVALID` and `CORRUPTED`
are terminal planning/response failures.

## Module dependency map

Generated from internal imports in `hidrocli/` and `hidro_orm/`; external
packages and Alembic migrations are omitted.

{module_map}

`hidrocli_docs` is build tooling; it reads the source and wiki, and is not part
of the runtime path.

## Client database relationships

Real foreign keys from SQLAlchemy metadata plus conceptual `JobRecords` links.
Only `Token.CredentialID` is database-enforced; `JobRecords.JobID` is a loose
reference to one of the four job tables.

{client_er}

## Job statuses

| Value | Status | Meaning |
| :--- | :--- | :--- |
| `1` | `PENDING` | Waiting to be requested. |
| `2` | `FAILED` | Request, validation, or write failure; retried while below the retry limit. |
| `3` | `INVALID` | The API rejected the request; terminal. |
| `4` | `CORRUPTED` | Invalid planning dates; terminal. |
| `5` | `COMPLETED` | Rows were written successfully. |
| `6` | `EMPTY` | The API succeeded but returned no items. |

## Storage layout

| Location | Contents |
| :--- | :--- |
| Hidro DB | Normalized reference and time-series tables. |
| Client DB | Credentials, token, base/station/series/telemetry job queues, and `JobRecords`. |
| `json/` | Raw ANA payload cache, optionally read with `--read-json` and written with `--save-json`. |
| `db/` | Default local database paths. |

---

*Generated from `hidrocli_docs/docs.py` by `hidro-docs`.*
"""


def slugify(text: str) -> str:
    """Return a lowercase, hyphen-separated slug for *text*."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.strip()).strip("-").lower()
    return slug or "page"


def hidro_model_filename(class_name: str) -> str:
    """Wiki page filename for a Hidro model."""
    return f"hidro-model-{slugify(class_name)}.md"


def client_model_filename(class_name: str) -> str:
    """Wiki page filename for a Client model."""
    return f"client-model-{slugify(class_name)}.md"


HELP_SNIPPETS = (
    (ROOT / "README.md", "## Usage", (sys.executable, "-m", "hidrocli", "--help")),
    (
        WIKI_DIR / "migration.md",
        "## Command overview",
        (sys.executable, "-m", "hidro_orm.cli", "--help"),
    ),
)

COLUMN_TYPES = {
    "BigInteger": "int",
    "DateTime": "datetime",
    "Float": "float",
    "Integer": "int",
    "SmallInteger": "int",
    "String": "str",
    "Text": "str",
}

DOC_TYPE = re.compile(
    r"^(int|float|string|str|datetime|date|bool)\s*:\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class Field:
    name: str
    type_name: str
    description: str
    markdown_name: bool = False
    ana: str | None = None
    primary_key: bool = False
    foreign_key: str | None = None
    nullable: bool = True
    unique: bool = False


@dataclass
class Group:
    title: str
    fields: list[Field] = field(default_factory=list)
    collapsible: bool = False


@dataclass
class Model:
    class_name: str
    title: str
    table: str | None
    description: str
    anchor: str
    groups: list[Group] = field(default_factory=list)
    extra_fields: list[Field] = field(default_factory=list)


def column_type(node: ast.AST) -> str:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return "unknown"
    if not node.args:
        return "unknown"
    arg = node.args[0]
    if isinstance(arg, ast.Name):
        return COLUMN_TYPES.get(arg.id, arg.id.lower())
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
        return COLUMN_TYPES.get(arg.func.id, arg.func.id.lower())
    return "unknown"


def split_doc(doc: str | None, fallback_type: str) -> tuple[str, str]:
    text = inspect.cleandoc(doc or "").strip()
    match = DOC_TYPE.match(text)
    if match:
        type_name = match.group(1).lower()
        text = match.group(2).strip()
    else:
        type_name = fallback_type

    if type_name == "string":
        type_name = "str"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    description = "\n".join(lines)
    if not description:
        description = "—"
    else:
        description = description[0].upper() + description[1:]
        if description[-1] not in ".!?":
            description += "."
    return type_name, description


def _literal(node: ast.AST):
    """Best-effort literal evaluation of an AST node."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def _column_flags(value: ast.Call) -> tuple[str | None, bool, str | None, bool, bool]:
    """Extract (ana, primary_key, foreign_key, nullable, unique) from a Column call."""
    ana = None
    primary_key = False
    foreign_key = None
    nullable = True
    unique = False

    for kw in value.keywords:
        if kw.arg == "info":
            info = _literal(kw.value)
            if isinstance(info, dict):
                ana = info.get("ana")
        elif kw.arg == "primary_key":
            primary_key = bool(_literal(kw.value))
        elif kw.arg == "nullable":
            nullable = bool(_literal(kw.value))
        elif kw.arg == "unique":
            unique = bool(_literal(kw.value))

    for arg in value.args:
        if (
            isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Name)
            and arg.func.id == "ForeignKey"
        ):
            target = _literal(arg.args[0]) if arg.args else None
            if isinstance(target, str):
                foreign_key = target

    return ana, primary_key, foreign_key, nullable, unique


def read_models(path: Path) -> list[Model]:
    tree = ast.parse(path.read_text())
    models: list[Model] = []

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue

        table = None
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == "__tablename__"
            ):
                table = ast.literal_eval(stmt.value)
                break

        fields: list[Field] = []
        body = node.body
        for index, stmt in enumerate(body[:-1]):
            if not (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and not stmt.targets[0].id.startswith("__")
            ):
                continue
            value = stmt.value
            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "Column"
            ):
                continue

            doc_node = body[index + 1]
            doc = None
            if (
                isinstance(doc_node, ast.Expr)
                and isinstance(doc_node.value, ast.Constant)
                and isinstance(doc_node.value.value, str)
            ):
                doc = doc_node.value.value

            type_name, description = split_doc(doc, column_type(value))
            ana, primary_key, foreign_key, nullable, unique = _column_flags(value)
            fields.append(
                Field(
                    name=stmt.targets[0].id,
                    type_name=type_name,
                    description=description,
                    ana=ana,
                    primary_key=primary_key,
                    foreign_key=foreign_key,
                    nullable=nullable,
                    unique=unique,
                )
            )

        if not fields:
            continue

        models.append(
            Model(
                class_name=node.name,
                title=node.name,
                table=table,
                description="",
                anchor="",
                groups=[Group("", fields)],
            )
        )

    return models


def by_names(*names: str) -> Callable[[str], bool]:
    accepted = set(names)
    return lambda name: name in accepted


def by_prefix(prefix: str) -> Callable[[str], bool]:
    return lambda name: name.startswith(prefix)


def apply_groups(
    fields: list[Field],
    rules: list[tuple[str, Callable[[str], bool], bool]],
) -> list[Group]:
    groups = [Group(title, collapsible=collapsible) for title, _, collapsible in rules]
    remaining: list[Field] = []
    for item in fields:
        for group, (_, predicate, _) in zip(groups, rules):
            if predicate(item.name):
                group.fields.append(item)
                break
        else:
            remaining.append(item)
    if remaining:
        groups.append(Group("Other", fields=remaining))
    return [group for group in groups if group.fields]


# Curated metadata: (model class, display title, table, description).
SHARED = [
    (
        "HidroBaseModel",
        "Shared fields",
        None,
        "Audit and identity columns inherited by every persisted model.",
        "shared-fields",
    ),
]

REFERENCE = [
    ("Basin", "Bacia", "Bacia", "Hydrographic basins.", "bacia-basin"),
    ("SubBasin", "SubBacia", "SubBacia", "Hydrographic sub-basins.", "subbacia-subbasin"),
    ("Entity", "Entidade", "Entidade", "Agencies and entities associated with stations.", "entidade-entity"),
    ("Township", "Municipio", "Municipio", "Municipalities.", "municipio-township"),
    ("River", "Rio", "Rio", "Rivers.", "rio-river"),
    ("State", "Estado", "Estado", "States and other South American countries.", "estado-state"),
    (
        "Station",
        "Estacao",
        "Estacao",
        "Hydrometeorological stations, including location, operator, observation periods, and network types.",
        "estacao-station",
    ),
]

SERIES = [
    (
        "Rain",
        "Chuvas",
        "Chuvas",
        "Monthly rainfall records with daily totals and status flags.",
        "chuvas-rain",
    ),
    (
        "Stage",
        "Cotas",
        "Cotas",
        "Monthly stage (water-level) records with daily values and status flags.",
        "cotas-stage",
    ),
    (
        "FlowRate",
        "Vazoes",
        "Vazoes",
        "Monthly flow-rate records with daily values and status flags.",
        "vazoes-flowrate",
    ),
    (
        "DischargeMeasurement",
        "ResumoDescarga",
        "ResumoDescarga",
        "Liquid-discharge measurement summaries.",
        "resumodescarga-dischargemeasurement",
    ),
    (
        "Sediments",
        "Sedimentos",
        "Sedimentos",
        "Sediment measurements and their corresponding liquid-discharge data.",
        "sedimentos-sediments",
    ),
    (
        "RatingCurve",
        "CurvaDescarga",
        "CurvaDescarga",
        "Stage-discharge rating curves, equations, and validity periods.",
        "curvadescarga-ratingcurve",
    ),
    (
        "WaterQuality",
        "QualAgua",
        "QualAgua",
        "Water-quality measurements. Parameter columns follow the ANA codes; status flags are stored in QualAguaStatus.",
        "qualagua-waterquality",
    ),
    (
        "WaterQualityStatus",
        "QualAguaStatus",
        "QualAguaStatus",
        "Status flags for each water-quality parameter.",
        "qualaguastatus-waterqualitystatus",
    ),
    (
        "Granulometry",
        "Granulometria",
        "Granulometria",
        "Granulometric analyses of bed material, bed load, and suspended sediment.",
        "granulometria-granulometry",
    ),
    (
        "CrossSection",
        "PerfilTransversal",
        "PerfilTransversal",
        "Cross-section surveys.",
        "perfiltransversal-crosssection",
    ),
    (
        "VerticalCrossSection",
        "PerfilTransversalVert",
        "PerfilTransversalVert",
        "Vertical measurements within cross-section surveys.",
        "perfiltransversalvert-verticalcrosssection",
    ),
    (
        "Telemetry",
        "Telemetria",
        "Telemetria",
        "Telemetric measurements, including sensor, adopted, and displayed values with status flags.",
        "telemetria-telemetry",
    ),
]

MODEL_INFO = {
    class_name: (title, table, description, anchor)
    for class_name, title, table, description, anchor in SHARED + REFERENCE + SERIES
}

EXTRA_FIELDS = {
    "Rain": [
        Field("`Chuva01`..`Chuva31`", "float", "Daily rainfall for days 1–31 of the month (mm).", True),
        Field("`Chuva01Status`..`Chuva31Status`", "int", "Status flag for each daily rainfall value.", True),
    ],
    "Stage": [
        Field("`Cota01`..`Cota31`", "float", "Daily stage for days 1–31 of the month (cm).", True),
        Field("`Cota01Status`..`Cota31Status`", "int", "Status flag for each daily stage value.", True),
    ],
    "FlowRate": [
        Field("`Vazao01`..`Vazao31`", "float", "Daily flow rate for days 1–31 of the month (m3/s).", True),
        Field("`Vazao01Status`..`Vazao31Status`", "int", "Status flag for each daily flow-rate value.", True),
    ],
    "WaterQualityStatus": [
        Field("`QualAgua001Status`..`QualAgua147Status`", "int", "Status flag for each water-quality parameter.", True),
    ],
}

FIELD_ORDER: dict[tuple[str, str], list[str]] = {
    ("Station", "Identification"): [
        "Codigo",
        "Nome",
        "CodigoAdicional",
        "BaciaCodigo",
        "SubBaciaCodigo",
        "RioCodigo",
        "MunicipioCodigo",
        "EstadoSigla",
    ],
    ("Station", "Location"): ["Latitude", "Longitude", "Altitude", "AreaDrenagem"],
    ("Station", "Operation"): [
        "OperadoraCodigo",
        "OperadoraUnidade",
        "OperadoraSubUnidade",
        "ResponsavelCodigo",
        "ResponsavelUnidade",
        "Operando",
        "UltimaAtualizacao",
    ],
    ("WaterQuality", "Measurement metadata"): [
        "Data",
        "NivelConsistencia",
        "NumMedicao",
        "EstacaoCodigo",
        "Choveu",
        "PosHorizColeta",
        "PosVertColeta",
        "Profundidade",
    ],
}

GROUP_RULES: dict[str, list[tuple[str, Callable[[str], bool], bool]]] = {
    "Station": [
        (
            "Identification",
            by_names(
                "Codigo",
                "Nome",
                "CodigoAdicional",
                "BaciaCodigo",
                "SubBaciaCodigo",
                "RioCodigo",
                "MunicipioCodigo",
                "EstadoSigla",
            ),
            False,
        ),
        ("Location", by_names("Latitude", "Longitude", "Altitude", "AreaDrenagem"), False),
        (
            "Operation",
            by_names(
                "OperadoraCodigo",
                "OperadoraUnidade",
                "OperadoraSubUnidade",
                "ResponsavelCodigo",
                "ResponsavelUnidade",
                "Operando",
                "UltimaAtualizacao",
            ),
            False,
        ),
        ("Observation periods", by_prefix("Periodo"), False),
        ("Station types", by_prefix("TipoEstacao"), False),
        ("Network types", by_prefix("TipoRede"), False),
    ],
    "WaterQuality": [
        (
            "Measurement metadata",
            by_names(
                "Data",
                "NivelConsistencia",
                "NumMedicao",
                "PosHorizColeta",
                "PosVertColeta",
                "Profundidade",
                "Choveu",
                "EstacaoCodigo",
            ),
            False,
        ),
        ("Water-quality parameters", lambda name: True, True),
    ],
    "Granulometry": [
        (
            "Sampling metadata",
            by_names(
                "EstacaoCodigo",
                "NivelConsistencia",
                "Data",
                "HoraInicial",
                "HoraFinal",
                "Cota",
                "Largura",
                "TipoAmostra",
                "TipoColeta",
                "TipoEquip",
                "ProfTotal",
                "OrdemColeta",
                "DistPTOInicial",
                "ChuvaUlt48",
            ),
            False,
        ),
        ("Bed material (`MatFundo*`)", by_prefix("MatFundo"), False),
        ("Bed load (`MatArraste*`)", by_prefix("MatArraste"), False),
        ("Suspended sediment (`MatSusp*`)", by_prefix("MatSusp"), False),
    ],
}


ENUM_ENTRY = re.compile(r"^\s*(\d+)\s*[-–—]\s*(.+?)\s*$")


def render_description(text: str) -> str:
    """Render a field description, folding trailing ``N - value`` enum lines."""
    escaped = [
        html.escape(line, quote=False).replace("|", "\\|")
        for line in text.split("\n")
    ]
    if not escaped:
        return "—"
    first_enum = next(
        (index for index, line in enumerate(escaped) if ENUM_ENTRY.match(line)),
        None,
    )
    if first_enum is None:
        return "<br>".join(escaped)

    lead = "<br>".join(escaped[:first_enum])
    values = "<br>".join(
        f"<strong>{match.group(1)}</strong> &mdash; {match.group(2)}"
        for line in escaped[first_enum:]
        if (match := ENUM_ENTRY.match(line))
    )
    return f"{lead}<br>{values}" if lead else values


def key_badges(item: Field) -> str:
    badges: list[str] = []
    if item.primary_key:
        badges.append("PK")
    if item.foreign_key:
        badges.append("FK")
    if item.unique:
        badges.append("UQ")
    if not item.nullable:
        badges.append("NOT NULL")
    return " · ".join(badges) if badges else "—"


def field_table(fields: list[Field]) -> list[str]:
    lines = [
        "| Field | Type | ANA | Key | Description |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for item in fields:
        name = item.name if item.markdown_name else f"`{item.name}`"
        description = render_description(item.description)
        if item.ana:
            ana = f"`{html.escape(str(item.ana), quote=False).replace('|', '\\|')}`"
        else:
            ana = "—"
        lines.append(
            f"| {name} | `{item.type_name}` | {ana} | {key_badges(item)} | {description} |"
        )
    return lines


def render_table(model: Model, group: Group, level: int = 4) -> list[str]:
    lines: list[str] = []
    if group.title:
        lines.append(f"{'#' * level} {group.title}")
        lines.append("")
    fields = group.fields
    if group.collapsible:
        lines.append("<details>")
        lines.append(f"<summary><strong>Show {len(fields)} fields</strong></summary>")
        lines.append("")
        lines.extend(field_table(fields))
        lines.append("")
        lines.append("</details>")
        lines.append("")
    else:
        lines.extend(field_table(fields))
        lines.append("")
    return lines


def er_diagram(relationships: list[tuple[str, str, str]]) -> list[str]:
    lines = ["```mermaid", "erDiagram"]
    for source, target, label in relationships:
        lines.append(f'    {source} ||--o{{ {target} : "{label}"')
    lines.append("```")
    return lines


def _module_name(path: Path, root: Path) -> str:
    """Return the dotted module name for a Python file under *root*."""

    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _module_id(name: str) -> str:
    """Return a Mermaid-safe node identifier for a module name."""

    return "m_" + name.replace(".", "_")


def discover_module_edges():
    """Return module nodes and internal import edges for the application.

    Only ``hidrocli`` and ``hidro_orm`` are scanned, and Alembic migrations are
    excluded. External imports are ignored.
    """

    modules = {}
    for package in ("hidrocli", "hidro_orm"):
        for path in (ROOT / package).rglob("*.py"):
            if (
                "__pycache__" in path.parts
                or "migrations" in path.parts
                or "build" in path.parts
            ):
                continue
            modules[_module_name(path, ROOT)] = path

    edges = set()
    for module, path in modules.items():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                targets = [node.module] if node.module else []
            elif isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            else:
                continue
            for target in targets:
                if target in modules and target != module:
                    edges.add((module, target))

    used = {name for edge in edges for name in edge}
    nodes = [(_module_id(name), name) for name in sorted(used)]
    return nodes, sorted(edges)


def _module_map() -> str:
    """Render the module dependency graph as a Mermaid block."""

    nodes, edges = discover_module_edges()
    lines = ["```mermaid", "flowchart LR"]
    lines.extend(f'    {node_id}["{label}"]' for node_id, label in nodes)
    lines.extend(f'    {source} --> {target}' for source, target in edges)
    lines.append("```")
    return "\n".join(lines)


def client_er_relationships():
    """Return client ER edges from real FKs plus conceptual JobRecords links."""

    from hidrocli.models.client import ClientBase

    relationships = set(CLIENT_CONCEPTUAL_ER)
    for table in ClientBase.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            relationships.add((
                foreign_key.column.table.name,
                table.name,
                "references",
            ))
    return sorted(relationships)


def _hidro_related(class_name: str) -> list[tuple[str, str]]:
    """Return (title, slug) links for models related to *class_name*."""
    table = MODEL_INFO[class_name][1]
    if not table:
        return []
    table_to_class = {
        MODEL_INFO[c][1]: c for c in MODEL_INFO if MODEL_INFO[c][1]
    }
    related: list[tuple[str, str]] = []
    for source, target, _ in HIDRO_ER:
        if source == table and target in table_to_class:
            related.append((MODEL_INFO[table_to_class[target]][0], hidro_model_filename(table_to_class[target])[:-3]))
        elif target == table and source in table_to_class:
            related.append((MODEL_INFO[table_to_class[source]][0], hidro_model_filename(table_to_class[source])[:-3]))
    return related


def render_model_page(
    model: Model,
    back_slug: str,
    back_label: str,
    related: list[tuple[str, str]] = (),
) -> str:
    heading = f"{model.title} ({model.class_name})" if model.table else model.title
    lines = [
        f"# {heading}",
        "",
        f"[← {back_label}]({back_slug})",
        "",
    ]
    metadata = f"*Model: `{model.class_name}`"
    if model.table:
        metadata += f" · Table: `{model.table}`"
    metadata += "*"
    lines.extend([metadata, "", model.description, ""])

    for group in model.groups:
        lines.extend(render_table(model, group, level=2))

    if model.extra_fields:
        lines.extend(
            render_table(model, Group("Generated columns", model.extra_fields), level=2)
        )

    if related:
        lines.extend(["## Related", ""])
        lines.append(" · ".join(f"[{label}]({slug})" for label, slug in related))
        lines.append("")

    lines.extend(["", f"[← {back_label}]({back_slug})", ""])
    return "\n".join(lines)


def _hydrate_models(models: list[Model]) -> dict[str, Model]:
    by_class = {model.class_name: model for model in models}
    for class_name, model in by_class.items():
        title, table, description, anchor = MODEL_INFO[class_name]
        model.title = title
        model.table = table
        model.description = description
        model.anchor = anchor
        rules = GROUP_RULES.get(class_name)
        if rules:
            model.groups = apply_groups(
                [f for group in model.groups for f in group.fields], rules
            )
            for group in model.groups:
                order = FIELD_ORDER.get((class_name, group.title))
                if order:
                    position = {name: index for index, name in enumerate(order)}
                    group.fields.sort(key=lambda item: position.get(item.name, len(order)))
        model.extra_fields = EXTRA_FIELDS.get(class_name, [])
    return by_class


def build_page(models: list[Model]) -> str:
    by_class = _hydrate_models(models)

    lines = [
        "# Hidro Models",
        "",
        "ORM models for the Hidro database. Field descriptions follow the ANA HIDRO 1.0 "
        "data dictionary (Manual do Usuário, Apêndice A) and the ANA Hidro WebServices payloads.",
        "",
        "Each model is documented on its own page. Browse the [shared fields](#shared-fields) "
        "and the reference and time-series tables below.",
        "",
        "## Relationships",
        "",
    ]
    lines.extend(er_diagram(HIDRO_ER))
    lines.extend(
        [
            "",
            "Cardinalities are conceptual: relationships are keyed by `EstacaoCodigo` "
            "and `RegistroID`, not database-enforced foreign keys.",
            "",
            "## Contents",
            "",
            "**Shared**",
            "",
            "- [Shared fields](#shared-fields)",
            "",
            "**Reference tables**",
            "",
        ]
    )
    for class_name, title, _, _, _ in REFERENCE:
        lines.append(f"- [{title}]({hidro_model_filename(class_name)})")

    lines.extend(["", "**Time-series tables**", ""])
    for class_name, title, _, _, _ in SERIES:
        lines.append(f"- [{title}]({hidro_model_filename(class_name)})")

    lines.extend(["", "## Shared fields", ""])
    for class_name, _, _, _, _ in SHARED:
        model = by_class[class_name]
        lines.append(model.description)
        lines.append("")
        for group in model.groups:
            lines.extend(field_table(group.fields))
            lines.append("")

    lines.extend(
        [
            "---",
            "",
            "*Generated from `hidrocli/models/hidro.py` by `hidro-docs`.*",
            "",
        ]
    )
    return "\n".join(lines)


CLIENT_AUTH = [
    (
        "Credentials",
        "Credentials",
        "ANA API credentials used to request access tokens.",
        "credentials",
    ),
    (
        "Token",
        "Token",
        "Cached access token and expiration; reused while valid.",
        "token",
    ),
]

CLIENT_JOBS = [
    (
        "HidroJob",
        "HidroJob (shared fields)",
        "Shared fields for every persistent job-queue entry.",
        "hidrojob-shared-fields",
    ),
    (
        "BaseJobs",
        "BaseJobs",
        "Jobs that refresh reference resources. Includes the shared `HidroJob` fields.",
        "basejobs",
    ),
    (
        "StationJobs",
        "StationJobs",
        "Jobs that refresh station inventory for one state. Includes the shared `HidroJob` fields.",
        "stationjobs",
    ),
    (
        "SeriesJobs",
        "SeriesJobs",
        "Jobs that request a station time-series window. Includes the shared `HidroJob` fields.",
        "seriesjobs",
    ),
    (
        "TelemetryJobs",
        "TelemetryJobs",
        "Jobs that request one telemetric station search window. Includes the shared `HidroJob` fields.",
        "telemetryjobs",
    ),
    (
        "JobRecords",
        "JobRecords",
        "Maps each written Hidro data row to the latest job that produced it.",
        "jobrecords",
    ),
]

CLIENT_INFO = {
    class_name: (title, description, anchor)
    for class_name, title, description, anchor in CLIENT_AUTH + CLIENT_JOBS
}


def _hydrate_client_models(models: list[Model]) -> dict[str, Model]:
    by_class = {model.class_name: model for model in models}
    for class_name, model in by_class.items():
        title, description, anchor = CLIENT_INFO[class_name]
        model.title = title
        model.table = None
        model.description = description
        model.anchor = anchor
    return by_class


def build_client_page(models: list[Model]) -> str:
    lines = [
        "# Client Models",
        "",
        "ORM models for the local client database. It stores ANA API credentials and "
        "tokens plus the persistent job queue used to synchronize the Hidro database.",
        "",
        "Each model is documented on its own page.",
        "",
        "## Contents",
        "",
        "**Authentication**",
        "",
    ]
    for class_name, title, _, _ in CLIENT_AUTH:
        lines.append(f"- [{title}]({client_model_filename(class_name)})")

    lines.extend(["", "**Job queue**", ""])
    for class_name, title, _, _ in CLIENT_JOBS:
        lines.append(f"- [{title}]({client_model_filename(class_name)})")

    lines.extend(
        [
            "",
            "---",
            "",
            "*Generated from `hidrocli/models/client.py` by `hidro-docs`.*",
            "",
        ]
    )
    return "\n".join(lines)


def build_architecture_page() -> str:
    """Render the application architecture, flow, lifecycle, and module maps."""

    return ARCH_PAGE.format(
        module_map=_module_map(),
        client_er="\n".join(er_diagram(client_er_relationships())),
    )


def _remove_stale(directory: Path, prefix: str, keep: set[str]) -> None:
    """Remove per-model pages that no longer match a model class."""
    for path in directory.glob(f"{prefix}*.md"):
        if path.name not in keep:
            path.unlink()
            print(f"removed {path}")


def _write(path: Path, content: str) -> None:
    path.write_text(content)
    print(f"wrote {path}")


def generate_models_page() -> None:
    """Regenerate the Hidro models index and one page per model."""
    if not OUTPUT_FILE.parent.is_dir():
        raise SystemExit(
            "wiki directory not found; run "
            "`git submodule update --init hidrocli_docs/wiki` first"
        )
    models = read_models(MODEL_FILE)
    by_class = _hydrate_models(models)
    _write(OUTPUT_FILE, build_page(models))

    keep = {hidro_model_filename(c) for c, *_ in REFERENCE + SERIES}
    _remove_stale(WIKI_DIR, "hidro-model-", keep)
    for class_name, *_ in REFERENCE + SERIES:
        page = render_model_page(
            by_class[class_name],
            "hidro-models",
            "Hidro Models",
            _hidro_related(class_name),
        )
        _write(WIKI_DIR / hidro_model_filename(class_name), page)


def generate_client_models_page() -> None:
    """Regenerate the Client models index and one page per model."""
    if not CLIENT_OUTPUT_FILE.parent.is_dir():
        raise SystemExit(
            "wiki directory not found; run "
            "`git submodule update --init hidrocli_docs/wiki` first"
        )
    models = read_models(CLIENT_MODEL_FILE)
    by_class = _hydrate_client_models(models)
    _write(CLIENT_OUTPUT_FILE, build_client_page(models))

    keep = {client_model_filename(c) for c, *_ in CLIENT_AUTH + CLIENT_JOBS}
    _remove_stale(WIKI_DIR, "client-model-", keep)
    for class_name, *_ in CLIENT_AUTH + CLIENT_JOBS:
        page = render_model_page(by_class[class_name], "client-models", "Client Models")
        _write(WIKI_DIR / client_model_filename(class_name), page)


def generate_architecture_page() -> None:
    """Regenerate the application architecture page."""
    if not WIKI_DIR.is_dir():
        raise SystemExit(
            "wiki directory not found; run "
            "`git submodule update --init hidrocli_docs/wiki` first"
        )
    _write(WIKI_DIR / "architecture.md", build_architecture_page())


def generate_sidebar() -> None:
    """Write the GitHub wiki sidebar with grouped, nested navigation."""
    lines = [
        "**Getting started**",
        "",
        "- [Home](Home)",
        "- [Architecture](architecture)",
        "- [Migration](migration)",
        "- [Use Cases](Use-Cases)",
        "",
        "**Modules**",
        "",
        "- [Config](config)",
        "- [Jobs](jobs)",
        "- [WebServices](webservices)",
        "",
        "**Databases**",
        "",
        "- [Hidro Database](hidro-database)",
        "- [Client Database](client-database)",
        "",
        "**Hidro Models**",
        "",
        "- [Overview](hidro-models)",
        "- Reference",
    ]
    for class_name, title, *_ in REFERENCE:
        lines.append(f"  - [{title}]({hidro_model_filename(class_name)[:-3]})")
    lines.append("- Time-series")
    for class_name, title, *_ in SERIES:
        lines.append(f"  - [{title}]({hidro_model_filename(class_name)[:-3]})")

    lines.extend(["", "**Client Models**", "", "- [Overview](client-models)"])
    for class_name, title, *_ in CLIENT_AUTH:
        lines.append(f"  - [{title}]({client_model_filename(class_name)[:-3]})")
    for class_name, title, *_ in CLIENT_JOBS:
        lines.append(f"  - [{title}]({client_model_filename(class_name)[:-3]})")

    _write(WIKI_DIR / "_Sidebar.md", "\n".join(lines) + "\n")


def generate_footer() -> None:
    """Write the GitHub wiki footer."""
    footer = "\n".join(
        [
            "---",
            "",
            "*Generated by `hidro-docs` from the "
            "[HidroCLI](https://github.com/csilab-ufop/HidroCLI) source. Data sourced "
            "from [ANA Hidro WebServices](https://www.snirh.gov.br/hidroweb/).*",
            "",
        ]
    )
    _write(WIKI_DIR / "_Footer.md", footer)


def copy_assets() -> None:
    """Copy repository image assets (e.g. the icon) into the wiki."""
    src = ROOT / "assets"
    if not src.is_dir():
        return
    dst = WIKI_DIR / "assets"
    dst.mkdir(exist_ok=True)
    for item in src.glob("*.png"):
        target = dst / item.name
        if not target.is_file() or target.read_bytes() != item.read_bytes():
            target.write_bytes(item.read_bytes())
            print(f"copied asset {item.name}")


def help_output(command: tuple[str, ...]) -> str:
    """Run a CLI help command and return its text."""
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(ROOT) if not pythonpath else f"{ROOT}{os.pathsep}{pythonpath}"
    )
    # argparse wraps help text using COLUMNS; pin it so generated docs are stable.
    env["COLUMNS"] = "80"
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(
            f"failed to generate help with {' '.join(command)}:\n{detail}"
        )
    return result.stdout.rstrip("\n")


FENCE_OPEN = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)$")
FENCE_CLOSE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})[ \t]*$")


def replace_help_block(path: Path, heading: str, command: tuple[str, ...]) -> None:
    """Replace the first fenced block under *heading* with *command* output."""
    if not path.is_file():
        raise SystemExit(f"{path}: help snippet file not found")
    original = path.read_text()
    lines = original.splitlines(keepends=True)

    headings = [
        index for index, line in enumerate(lines) if line.strip() == heading
    ]
    if len(headings) != 1:
        raise SystemExit(
            f"{path}: expected exactly one {heading!r} heading, "
            f"found {len(headings)}"
        )

    open_index = None
    open_fence = None
    for index in range(headings[0] + 1, len(lines)):
        if re.match(r"^#{1,6}\s", lines[index]):
            break
        match = FENCE_OPEN.match(lines[index].rstrip("\n"))
        if match:
            open_index = index
            open_fence = match.group("fence")
            break
    if open_index is None:
        raise SystemExit(f"{path}: no fenced block found under {heading!r}")

    close_index = None
    for index in range(open_index + 1, len(lines)):
        match = FENCE_CLOSE.match(lines[index].rstrip("\n"))
        if (
            match
            and match.group("fence")[0] == open_fence[0]
            and len(match.group("fence")) >= len(open_fence)
        ):
            close_index = index
            break
    if close_index is None:
        raise SystemExit(f"{path}: unterminated fenced block under {heading!r}")

    output = help_output(command)
    body = [f"{line}\n" for line in output.splitlines()]
    updated = "".join(lines[: open_index + 1] + body + lines[close_index:])
    if updated != original:
        path.write_text(updated)
        print(f"updated {path} ({heading})")


def update_help_blocks() -> None:
    """Refresh the CLI help snippets embedded in the documentation."""
    for path, heading, command in HELP_SNIPPETS:
        replace_help_block(path, heading, command)


def run_pydoc_markdown() -> None:
    """Run pydoc-markdown from the docs project."""
    if importlib.util.find_spec("pydoc_markdown") is None:
        raise SystemExit(
            "pydoc-markdown is not installed; run "
            "`.venv/bin/python -m pip install -e ./hidrocli_docs`"
        )
    subprocess.run(
        [sys.executable, "-c", "from pydoc_markdown.main import cli; cli()"],
        cwd=DOCS_ROOT,
        check=True,
    )


def post_process_wiki() -> None:
    """Add the separator layout used by the generated wiki pages."""
    for path in sorted(WIKI_DIR.glob("*.md")):
        if path.name.startswith("_"):
            continue
        text = path.read_text()
        text = re.sub(
            r'(<a id=".*?"></a>\n\n## )',
            r'\n---\n\n\1',
            text,
        )
        text = re.sub(
            r'(?<!\n---\n\n)(?=^#### )',
            r'\n---\n\n',
            text,
            flags=re.MULTILINE,
        )
        path.write_text(text)

    # pydoc-markdown's mkdocs renderer writes these files, but the published
    # documentation is a GitHub wiki, not an MkDocs site.
    for artifact in ("mkdocs.yml", ".generated-files.txt"):
        (WIKI_DIR / artifact).unlink(missing_ok=True)


def polish_module_pages() -> None:
    """Give pydoc-markdown module pages a consistent title and clean escapes."""
    for name, title in MODULE_TITLES.items():
        path = WIKI_DIR / f"{name}.md"
        if not path.is_file():
            continue
        original = path.read_text()
        # Rewrite the first H1 (the module name) to a friendlier title.
        text = re.sub(r"(?m)^#\s+[^\n]+$", f"# {title}", original, count=1)
        # Unescape underscores pydoc-markdown escapes in headings/signatures.
        text = text.replace(r"\_", "_")
        if text != original:
            path.write_text(text)
            print(f"polished {path}")


def main() -> None:
    """Refresh help snippets, build every wiki page, and regenerate models."""
    update_help_blocks()
    run_pydoc_markdown()
    post_process_wiki()
    polish_module_pages()
    generate_models_page()
    generate_client_models_page()
    generate_architecture_page()
    generate_sidebar()
    generate_footer()
    copy_assets()


if __name__ == "__main__":
    main()

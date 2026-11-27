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

import sys

import pytest

from hidrocli_docs import docs


def test_replace_help_block_updates_only_the_target_section(tmp_path):
    path = tmp_path / "README.md"
    path.write_text(
        "## Usage\n\n```\nstale\n```\n\n## Other\n\n```\nkeep\n```\n"
    )

    docs.replace_help_block(
        path,
        "## Usage",
        (sys.executable, "-c", "print('usage: demo')"),
    )

    text = path.read_text()
    assert "usage: demo" in text
    assert "stale" not in text
    assert "keep" in text


def test_replace_help_block_is_idempotent(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("## Usage\n\n```text\nstale\n```\n")
    command = (sys.executable, "-c", "print('usage: demo')")

    docs.replace_help_block(path, "## Usage", command)
    first = path.read_text()
    docs.replace_help_block(path, "## Usage", command)

    assert path.read_text() == first


def test_client_page_includes_job_records():
    models = docs.read_models(docs.CLIENT_MODEL_FILE)

    page = docs.build_client_page(models)

    assert "JobRecords" in page


def test_replace_help_block_rejects_missing_heading(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("## Other\n\n```\nstale\n```\n")

    with pytest.raises(SystemExit, match="expected exactly one"):
        docs.replace_help_block(
            path,
            "## Usage",
            (sys.executable, "-c", "print('usage: demo')"),
        )


def _fields(model):
    return [field for group in model.groups for field in group.fields]


def test_read_models_captures_ana_and_keys():
    models = docs.read_models(docs.MODEL_FILE)
    by_class = {m.class_name: m for m in models}

    station = {f.name: f for f in _fields(by_class["Station"])}
    assert station["Codigo"].ana == "codigoestacao"
    assert station["Codigo"].unique is True

    shared = {f.name: f for f in _fields(by_class["HidroBaseModel"])}
    assert shared["RegistroID"].primary_key is True

    status = {f.name: f for f in _fields(by_class["WaterQualityStatus"])}
    assert status["QualAguaID"].foreign_key == "QualAgua.RegistroID"
    assert status["QualAguaID"].nullable is False


def test_build_page_links_to_per_model_pages():
    models = docs.read_models(docs.MODEL_FILE)
    page = docs.build_page(models)
    assert "```mermaid" in page
    assert "erDiagram" in page
    assert "[Estacao](hidro-model-station.md)" in page
    assert "[Chuvas](hidro-model-rain.md)" in page


def test_build_client_page_links_to_per_model_pages():
    models = docs.read_models(docs.CLIENT_MODEL_FILE)
    page = docs.build_client_page(models)
    assert "[JobRecords](client-model-jobrecords.md)" in page


def test_render_description_folds_enum_values():
    out = docs.render_description(
        "River jurisdiction.\n1 - Federal\n2 - State\n3 - Undefined."
    )
    assert "<strong>1</strong>" in out
    assert "&mdash;" in out
    assert "<details>" not in out


def test_render_model_page_includes_related_links():
    models = docs.read_models(docs.MODEL_FILE)
    by_class = docs._hydrate_models(models)
    page = docs.render_model_page(
        by_class["WaterQuality"],
        "hidro-models",
        "Hidro Models",
        docs._hidro_related("WaterQuality"),
    )
    assert "## Related" in page
    assert "[QualAguaStatus](hidro-model-waterqualitystatus)" in page


def test_generate_sidebar_writes_grouped_nav(tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "WIKI_DIR", tmp_path)
    docs.generate_sidebar()
    text = (tmp_path / "_Sidebar.md").read_text()
    assert "**Hidro Models**" in text
    assert "[Architecture](architecture)" in text
    assert "[Overview](hidro-models)" in text
    assert "[Bacia](hidro-model-basin)" in text
    assert "[JobRecords](client-model-jobrecords)" in text


def test_architecture_page_has_graphs():
    page = docs.build_architecture_page()
    assert "flowchart" in page
    assert "stateDiagram-v2" in page
    assert "erDiagram" in page
    assert "Credentials" in page
    assert "EMPTY" in page


def test_discover_module_edges_is_internal_only():
    nodes, edges = docs.discover_module_edges()
    assert ("hidrocli.jobs.runner", "hidrocli.webservices") in edges
    assert ("hidrocli.jobs.runner", "hidrocli.database") in edges
    assert all(
        source.startswith(("hidrocli", "hidro_orm"))
        and target.startswith(("hidrocli", "hidro_orm"))
        for source, target in edges
    )
    assert any(label == "hidrocli.jobs.runner" for _, label in nodes)
    assert all("build" not in label for _, label in nodes)


def test_client_er_relationships_combines_fks_and_concepts():
    relationships = docs.client_er_relationships()
    assert ("Credentials", "Token", "references") in relationships
    assert ("BaseJobs", "JobRecords", "produces") in relationships
    assert ("TelemetryJobs", "JobRecords", "produces") in relationships


def test_generate_footer_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "WIKI_DIR", tmp_path)
    docs.generate_footer()
    text = (tmp_path / "_Footer.md").read_text()
    assert "hidro-docs" in text

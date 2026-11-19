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


def test_replace_help_block_rejects_missing_heading(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("## Other\n\n```\nstale\n```\n")

    with pytest.raises(SystemExit, match="expected exactly one"):
        docs.replace_help_block(
            path,
            "## Usage",
            (sys.executable, "-c", "print('usage: demo')"),
        )

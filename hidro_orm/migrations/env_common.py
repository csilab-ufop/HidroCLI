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

"""Shared Alembic environment used by both migration chains."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from hidro_orm.schema import (
    DbKind,
    make_include_object,
    metadata_for,
    sqlite_url,
)


def _configure(*, target_metadata, include_object, **kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
        render_as_batch=False,
        **kwargs,
    )


def _run_offline(config, target_metadata, include_object) -> None:
    _configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_online(config, target_metadata, include_object) -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


def run_migrations(kind: DbKind | str) -> None:
    """Run Alembic for the selected database chain."""

    kind = DbKind(kind)
    config = context.config

    if (
        config.config_file_name is not None
        and config.get_section("loggers") is not None
    ):
        fileConfig(config.config_file_name)

    options = context.get_x_argument(as_dictionary=True)
    db_path = options.get("db_path")
    if db_path:
        config.set_main_option("sqlalchemy.url", sqlite_url(db_path))

    target_metadata = metadata_for(kind)
    include_object = make_include_object(target_metadata)
    if context.is_offline_mode():
        _run_offline(config, target_metadata, include_object)
    else:
        _run_online(config, target_metadata, include_object)

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

"""Command line interface for HidroCLI database migrations."""

from __future__ import annotations

import argparse
import sys
import traceback

from hidro_orm import runner
from hidro_orm.schema import DbKind

TARGETS = {
    "hidro": (DbKind.HIDRO,),
    "client": (DbKind.CLIENT,),
    "all": (DbKind.HIDRO, DbKind.CLIENT),
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hidro-orm",
        description=(
            "Manage Alembic schema revisions for the Hidro and Client "
            "databases."
        ),
        epilog=(
            "Examples:\n"
            "  hidro-orm --hidro db/hidro.db hidro current\n"
            "  hidro-orm --hidro db/hidro.db hidro stamp v0.0.0\n"
            "  hidro-orm --hidro db/hidro.db --client db/client.db all upgrade"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--hidro", default="db/hidro.db", help="Hidro database path")
    parser.add_argument("--client", default="db/client.db", help="Client database path")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show Alembic logging and full tracebacks",
    )
    parser.add_argument(
        "target",
        choices=tuple(TARGETS),
        help="Database chain to operate on: hidro, client, or all",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    upgrade = subparsers.add_parser("upgrade", help="Apply migrations")
    upgrade.add_argument("revision", nargs="?", default="head")

    stamp = subparsers.add_parser("stamp", help="Adopt a legacy database")
    stamp.add_argument("revision")

    subparsers.add_parser("current", help="Show the current revision")
    subparsers.add_parser("history", help="Show the revision chain")
    subparsers.add_parser("heads", help="Show the head revisions")
    subparsers.add_parser("check", help="Compare ORM metadata with the database")

    return parser


def _db_path(args: argparse.Namespace, kind: DbKind) -> str:
    return args.hidro if kind is DbKind.HIDRO else args.client


def _handle(args: argparse.Namespace) -> int:
    kinds = TARGETS[args.target]

    if args.command == "history":
        for kind in kinds:
            print(f"{kind.value}:")
            revisions = runner.history(kind)
            if not revisions:
                print("  (no revisions)")
            for revision in revisions:
                source = revision.down_revision or "base"
                description = f": {revision.doc}" if revision.doc else ""
                print(f"  {revision.revision} <- {source}{description}")
        return 0

    if args.command == "heads":
        for kind in kinds:
            print(f"{kind.value}: {', '.join(runner.heads(kind))}")
        return 0

    if args.command == "current":
        for kind in kinds:
            path = _db_path(args, kind)
            print(f"{kind.value}: {runner.current(kind, path)} ({path})")
        return 0

    if args.command == "check":
        failed = False
        for kind in kinds:
            path = _db_path(args, kind)
            diff = runner.check(kind, path)
            if diff:
                failed = True
                print(f"{kind.value}: drift detected in {path}")
                for item in diff:
                    print(f"  {item}")
            else:
                print(f"{kind.value}: ok ({path})")
        return 1 if failed else 0

    if args.command == "stamp":
        for kind in kinds:
            path = _db_path(args, kind)
            revision = runner.stamp(kind, path, args.revision)
            print(f"{kind.value}: stamped {revision} ({path})")
        return 0

    if args.command == "upgrade":
        for kind in kinds:
            path = _db_path(args, kind)
            runner.upgrade(kind, path, args.revision, quiet=not args.verbose)
            print(f"{kind.value}: upgraded to {args.revision} ({path})")
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    """Run the migration CLI and return a process exit code."""

    args = _build_parser().parse_args(argv)
    try:
        return _handle(args)
    except runner.MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        if args.verbose:
            traceback.print_exc()
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

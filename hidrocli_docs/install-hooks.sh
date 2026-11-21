#!/bin/sh
# Install the HidroCLI repository hooks for this clone.
#
# Enables the versioned hooks in .githooks/, including the pre-push hook that
# regenerates and publishes the documentation before main is pushed.

set -eu

cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
printf 'Installed git hooks from .githooks.\n'

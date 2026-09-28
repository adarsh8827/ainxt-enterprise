# SPDX-License-Identifier: MIT
"""External-sources catalog crawler (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md).

Builds the pointer-file catalog that lives on the `ecosystem-index` orphan
branch (never on `main` or any feature branch) -- this package's code
itself lives on `main`, imported by a small script the crawl workflow
runs after checking out that branch into a scratch directory.
"""

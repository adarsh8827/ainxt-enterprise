#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ============================================================
# Task B-17 (M3): generates docs/ecosystem/openapi.json from
# routers/ecosystem_router.py + routers/ecosystem_events_router.py's own
# route/response-model definitions.
#
# Builds a standalone FastAPI app mounting just the two ecosystem
# routers, rather than importing gateway.py itself -- gateway.py's own
# module-level import chain runs core.ckms.load_at_boot() and expects a
# large set of env vars/secrets to already be configured, which a CI
# codegen job (and this being a "does the checked-in spec still match
# the code" drift check, not an integration test) has no business
# depending on. Both routers are self-contained fastapi.APIRouter objects
# with no gateway-specific state, so this produces the same paths/schemas
# the real mounted routers would, without gateway.py's own boot cost.
#
# Usage:
#   python scripts/ecosystem/generate_openapi.py           # regenerate the spec file
#   python scripts/ecosystem/generate_openapi.py --check   # regenerate in-memory, diff
#                                                           # against the committed file,
#                                                           # exit 1 on drift (the CI job)
# ============================================================

from __future__ import annotations

import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO_ROOT)

_OUTPUT_PATH = os.path.join(_REPO_ROOT, "docs", "ecosystem", "openapi.json")


def _build_spec() -> dict:
    from fastapi import FastAPI

    from routers.ecosystem_events_router import router as events_router
    from routers.ecosystem_router import router as items_router

    app = FastAPI(title="AiNxt Ecosystem Marketplace API", version="2026.09.1")
    app.include_router(items_router, prefix="/ainxt/v1/api")
    app.include_router(events_router, prefix="/ainxt/v1/api")
    return app.openapi()


def main() -> int:
    check_only = "--check" in sys.argv
    spec = _build_spec()
    rendered = json.dumps(spec, indent=2, sort_keys=True) + "\n"

    if check_only:
        if not os.path.exists(_OUTPUT_PATH):
            print(f"MISSING: {_OUTPUT_PATH} does not exist -- run without --check to generate it.")
            return 1
        with open(_OUTPUT_PATH, encoding="utf-8") as f:
            committed = f.read()
        if committed != rendered:
            print(
                f"DRIFT: {_OUTPUT_PATH} does not match what routers/ecosystem_router.py + "
                "routers/ecosystem_events_router.py currently generate. Run "
                "'python scripts/ecosystem/generate_openapi.py' and commit the result."
            )
            return 1
        print(f"OK: {_OUTPUT_PATH} matches the current router definitions.")
        return 0

    os.makedirs(os.path.dirname(_OUTPUT_PATH), exist_ok=True)
    with open(_OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"wrote {_OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

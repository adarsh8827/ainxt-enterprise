#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Ecosystem marketplace — admin catalog import (task, 2026-09-28).

The ONE supported way to bulk-load external catalog items (starter set,
later External-sources phase) — wraps create_service.create_via_import()
with the same license/gate/attribution pipeline any other import already
goes through (pinned SHA, license inheritance evidence, full gate), as
Discover catalog items (community tier, not org-wide auto-provisioned).

Must run INSIDE a container sharing the gate-worker's object-storage mount
(store/ecosystem_object_storage.py's assert_local_storage_root_is_mounted(),
called first, refuses to proceed otherwise). Real incident, 2026-09-28: a
previous ad hoc host-side script wrote 8 real skills' object bytes to a
plain host directory the gate-worker container could never see — every
one of those 8 gate runs then failed once retried, but only after hours of
investigating what first looked like an unrelated hang (see
docs/ecosystem/design/CHANGELOG.md's dated entry). This script exists so
that never happens again via a bespoke one-off script.

Usage (inside the gateway container):
    docker exec ainxt-gateway python -m scripts.ecosystem.admin_import starter \\
        --org-id e2e-test-org --created-by <user_id>

`starter` imports docs/ecosystem/catalog/STARTER_CATALOG below. A custom
batch can be supplied instead via --specs-json (a JSON list of the same
{"namespace", "category", "ref"} dicts).
"""

from __future__ import annotations

import argparse
import json
import sys

# The 8 approved starter-catalog skills (see docs/ecosystem/catalog/
# starter-approved.md for the license evidence, compatibility tag, and
# provenance/neutrality review backing each one). nidhinjs/prompt-master
# was reviewed and excluded — its content extensively names specific AI
# products/vendors throughout, a real, direct violation of this platform's
# own neutrality rule — it is deliberately not one of these 8.
STARTER_CATALOG: list[dict] = [
    {
        "namespace": "addyosmani/code-review-and-quality", "category": "engineering",
        "ref": "addyosmani/agent-skills@2686b620fc1fed2e8f60c704839c766b8594c6b6#skills/code-review-and-quality",
    },
    {
        "namespace": "addyosmani/security-and-hardening", "category": "engineering",
        "ref": "addyosmani/agent-skills@2686b620fc1fed2e8f60c704839c766b8594c6b6#skills/security-and-hardening",
    },
    {
        "namespace": "addyosmani/documentation-and-adrs", "category": "engineering",
        "ref": "addyosmani/agent-skills@2686b620fc1fed2e8f60c704839c766b8594c6b6#skills/documentation-and-adrs",
    },
    {
        "namespace": "addyosmani/api-and-interface-design", "category": "engineering",
        "ref": "addyosmani/agent-skills@2686b620fc1fed2e8f60c704839c766b8594c6b6#skills/api-and-interface-design",
    },
    {
        "namespace": "wshobson/postmortem-writing", "category": "operations",
        "ref": "wshobson/agents@9b15b34b0bfc13a815cbfc2366e14ea549e09422#plugins/incident-response/skills/postmortem-writing",
    },
    {
        "namespace": "wshobson/incident-runbook-templates", "category": "operations",
        "ref": "wshobson/agents@9b15b34b0bfc13a815cbfc2366e14ea549e09422#plugins/incident-response/skills/incident-runbook-templates",
    },
    {
        "namespace": "wshobson/sql-optimization-patterns", "category": "engineering",
        "ref": "wshobson/agents@9b15b34b0bfc13a815cbfc2366e14ea549e09422#plugins/developer-essentials/skills/sql-optimization-patterns",
    },
    {
        "namespace": "mattpocock/diagnosing-bugs", "category": "engineering",
        "ref": "mattpocock/skills@c55ee46073ed923f86ce59a5eb3b6d895095d1b7#skills/engineering/diagnosing-bugs",
    },
]


def import_batch(specs: list[dict], *, org_id: str, created_by: str, catalog_scope: str = "org_private") -> list[dict]:
    """catalog_scope (item 6 fix, 2026-09-28): real bug found live -- this
    ran every import (including the `starter` batch) with the implicit
    'org_private' default, contradicting the starter batch's own
    docstring/docs/ecosystem/catalog/starter-approved.md description as
    "Discover catalog items (community tier, not org-wide
    auto-provisioned)" -- an org_private item is never visible to any
    OTHER org's Discover, and (as of a separate fix landing the same day)
    isn't even visible to its OWN org's Discover anymore, so the 8 starter
    skills were invisible everywhere. `main()` below now defaults the
    `starter` batch specifically to 'central_index'; a custom
    --specs-json batch keeps the safe 'org_private' default unless the
    caller explicitly opts in, since a custom batch might legitimately be
    a private, org-specific import rather than a global-catalog one.
    caller_permissions is hardcoded to {"marketplace:admin_sources"} --
    this script only ever runs as a deliberate, in-container admin action
    (see this module's own docstring), never behind a caller-supplied
    token, so there is no real "permissions" to thread through; this is
    what satisfies create_via_import()'s own admin-tier gate on
    catalog_scope='central_index'.
    """
    from store.ecosystem_object_storage import assert_local_storage_root_is_mounted

    assert_local_storage_root_is_mounted()

    from services.ecosystem.create_service import create_via_import

    results = []
    for spec in specs:
        try:
            result = create_via_import(
                org_id=org_id, created_by=created_by, item_type="skill",
                namespace=spec["namespace"], category=spec["category"],
                kind="github_repo", ref=spec["ref"],
                catalog_scope=catalog_scope, caller_permissions={"marketplace:admin_sources"},
            )
            results.append({"namespace": spec["namespace"], "ok": True, **result})
        except Exception as exc:
            results.append({"namespace": spec["namespace"], "ok": False, "error": str(exc)})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", choices=["starter"], help="Which built-in batch to import")
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--created-by", required=True, help="User id the import is attributed to / auto-installed for")
    parser.add_argument("--specs-json", default=None, help="Override the batch with a custom JSON list of {namespace, category, ref}")
    parser.add_argument(
        "--catalog-scope", default=None, choices=["org_private", "central_index"],
        help="Override the batch's default catalog scope. Unset: 'central_index' for the built-in 'starter' "
             "batch (a global Discover-catalog item, matching its own documented intent), 'org_private' for "
             "a custom --specs-json batch (safe default -- a custom batch might legitimately be a private import).",
    )
    args = parser.parse_args()

    specs = json.loads(args.specs_json) if args.specs_json else STARTER_CATALOG
    catalog_scope = args.catalog_scope or ("central_index" if args.batch == "starter" and args.specs_json is None else "org_private")

    results = import_batch(specs, org_id=args.org_id, created_by=args.created_by, catalog_scope=catalog_scope)

    failed = [r for r in results if not r["ok"]]
    for r in results:
        if r["ok"]:
            print(
                f"OK {r['namespace']}: item_id={r['item_id']} version_id={r['version_id']} "
                f"gate_run_id={r.get('gate_run_id')} compatibility={r.get('compatibility')}"
            )
        else:
            print(f"FAIL {r['namespace']}: {r['error']}")

    print(f"\n{len(results) - len(failed)}/{len(results)} imported successfully.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

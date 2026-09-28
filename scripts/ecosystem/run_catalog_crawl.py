# SPDX-License-Identifier: MIT
# ============================================================
# Entry point the crawl workflow (.github/workflows/ecosystem-catalog-
# crawl.yml) actually calls. Reads sources.yaml/yanked.yaml from the
# `main` checkout, writes the built pointer files + index into a
# separate `ecosystem-index` branch checkout, signs the index shards,
# and prints the crawl report to stdout (captured into the job summary
# by the workflow -- this is stop point 2's artifact). This script never
# runs `git` itself; the workflow's own steps own the checkout/commit/push
# against the `ecosystem-index` branch.
#
# Usage:
#   python -m scripts.ecosystem.run_catalog_crawl \
#     --sources docs/ecosystem/catalog/sources.yaml \
#     --yanked docs/ecosystem/catalog/yanked.yaml \
#     --output-dir /path/to/ecosystem-index-checkout
# ============================================================

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from services.ecosystem.catalog_crawler.crawl import run_crawl


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--yanked", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sign", action="store_true", help="Sign the built index shards (needs an ambient CI OIDC credential -- see signing.py).")
    parser.add_argument(
        "--verify-after-sign",
        action="store_true",
        help=(
            "Immediately re-verify each shard's freshly-produced signature against "
            "ECOSYSTEM_CATALOG_TRUSTED_SIGNER (env var, required when this flag is set) before "
            "returning success -- requires --sign. Fails closed: a signing bug that produces a "
            "bundle this same process can't verify against its own trusted signer must stop the "
            "job before the commit/push step ever runs, not be caught later by an installer."
        ),
    )
    args = parser.parse_args()

    if args.verify_after_sign and not args.sign:
        parser.error("--verify-after-sign requires --sign")

    report = run_crawl(args.sources, args.yanked, args.output_dir)
    print(report.to_markdown())

    if args.sign:
        from services.ecosystem.catalog_crawler.signing import sign_index_bytes

        if args.verify_after_sign:
            import os

            from services.ecosystem.catalog_crawler.signing import trusted_signer_from_env, verify_index_bytes

            raw_trusted_signer = os.environ.get("ECOSYSTEM_CATALOG_TRUSTED_SIGNER")
            if not raw_trusted_signer:
                print("ERROR: --verify-after-sign requires ECOSYSTEM_CATALOG_TRUSTED_SIGNER to be set", file=sys.stderr)
                return 1
            trusted_signer = trusted_signer_from_env(raw_trusted_signer)

        index_dir = Path(args.output_dir) / "index"
        for index_file in sorted(index_dir.glob("*.json")):
            data = index_file.read_bytes()
            bundle = sign_index_bytes(data)
            if args.verify_after_sign:
                verify_index_bytes(data, bundle, trusted_signer)
                print(f"verified {index_file.name} against ECOSYSTEM_CATALOG_TRUSTED_SIGNER")
            (index_file.with_suffix(index_file.suffix + ".sigstore")).write_bytes(bundle)
            print(f"signed {index_file.name} -> {index_file.name}.sigstore")

    return 0 if report.excluded_count == 0 or report.included_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

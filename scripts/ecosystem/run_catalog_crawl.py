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
    args = parser.parse_args()

    report = run_crawl(args.sources, args.yanked, args.output_dir)
    print(report.to_markdown())

    if args.sign:
        from services.ecosystem.catalog_crawler.signing import sign_index_bytes

        index_dir = Path(args.output_dir) / "index"
        for index_file in sorted(index_dir.glob("*.json")):
            data = index_file.read_bytes()
            bundle = sign_index_bytes(data)
            (index_file.with_suffix(index_file.suffix + ".sigstore")).write_bytes(bundle)
            print(f"signed {index_file.name} -> {index_file.name}.sigstore")

    return 0 if report.excluded_count == 0 or report.included_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

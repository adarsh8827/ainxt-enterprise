# ecosystem-index

This branch has **no shared history with `main`** (created via `git checkout --orphan`) and holds only the built external-sources catalog — pointer files, never skill file bytes. See `docs/ecosystem/EXTERNAL_SOURCES_PLAN.md` on `main` for the full design.

## Contents

- `catalog/<item_type>/<publisher>/<name>.yaml` — one pointer entry per catalog item (the reviewed source of truth).
- `index/<item_type>.json` — the same data flattened into one array per item type; what an installation actually fetches over HTTP.
- `index/<item_type>.json.sigstore` — a detached Sigstore bundle, produced by the crawl workflow's own GitHub Actions OIDC identity (keyless signing — no key stored anywhere). Verification is offline by default against a pinned trust root; see `services/ecosystem/catalog_crawler/signing.py` on `main`.
- `yanked.yaml` — namespaces removed from the catalog (a maintainer edit on `main`'s own `docs/ecosystem/catalog/yanked.yaml`, applied by the crawler here).

## How this branch is updated

`.github/workflows/ecosystem-catalog-crawl.yml` (on `main`) checks out this branch, runs the crawler against `main`'s own `docs/ecosystem/catalog/sources.yaml`, signs the result, and commits/pushes back here — scheduled daily plus manual dispatch. Routine crawl updates commit directly; `sources.yaml`/`yanked.yaml` changes always go through a normal reviewed PR on `main` first.

## History

This branch's commit history grows with every crawl. Squashing it periodically (to keep the branch lean — pointer files only, but the *history* of them isn't bounded) is a maintainer ops action, not something the crawl workflow does automatically.

## No ainxt-operated server

Nothing in this branch, or the workflow that updates it, involves any ainxt-operated service. Sources are public (GitHub repositories, well-known-site indexes, the official MCP Registry); this branch is the only place the crawl's output is published.

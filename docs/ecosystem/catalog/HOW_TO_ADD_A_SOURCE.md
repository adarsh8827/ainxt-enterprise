# How to add a catalog source

This is the plain-steps version of docs/ecosystem/EXTERNAL_SOURCES_PLAN.md
for the common case: you found a public repo/site you want the external
catalog crawler to index.

## Which file to edit

The crawler reads **`docs/ecosystem/catalog/sources.yaml`** — the copy
checked into this repo (`main`, or whatever branch/commit actually
triggered the crawl workflow run). It does **not** read anything from the
`ecosystem-index` branch: that orphan branch holds only the crawler's
*output* (the pointer files under `catalog/` and the built `index/`,
committed by `.github/workflows/ecosystem-catalog-crawl.yml`'s own last
step) — never its input. `yanked.yaml` works the same way: the workflow
reads `docs/ecosystem/catalog/yanked.yaml` from the main checkout, not
from `ecosystem-index`.

So: to add, disable, or change a source, edit
`docs/ecosystem/catalog/sources.yaml` on `main` via a normal reviewed PR.
Never edit anything under `ecosystem-index` by hand — the crawl workflow
owns that branch entirely.

## Steps

1. **Check the license first, before anything else.** Only MIT or
   Apache-2.0 is ever allowed (`services/ecosystem/license_policy.py`).
   For a GitHub repo, GitHub's own license-detection API is one signal;
   also open the actual LICENSE file, since the API can misdetect (see
   the `activepieces/activepieces` note further down in `sources.yaml` —
   the API reported "NOASSERTION" for a real, plain MIT file). For a
   generic git host there's no API to ask at all — the root LICENSE
   file's own text is the only signal, so read it yourself.

2. **Check neutrality.** Skim a few SKILL.md files for AI-vendor/product
   names (`services/ecosystem/catalog_crawler/neutrality_check.py` has
   the exact list this platform's neutrality filter checks against). A
   repo doesn't have to be 100% clean — the crawler excludes offending
   items individually and reports why — but if most of the repo fails,
   it's usually not worth adding at all (see `sources.yaml`'s own
   commented-out exclusions for real examples of this judgment call).

3. **Check for anything already excluded.** `sources.yaml`'s own header
   comments list sources considered and rejected, with the reason —
   check there first so you don't re-litigate a decision that was
   already made.

4. **Add the entry**, under the right top-level key:

   - **GitHub repo** → `github_repos:`
     ```yaml
     - repo: someone/their-skills-repo
       category: engineering          # must be a real taxonomy category — see step 5
       tags: [whatever, fits]
       tos_note: "Public GitHub repo, MIT (repo-root LICENSE). One sentence on why this is safe to crawl."
     ```
     Optional: `include_paths`/`exclude_paths` (scope to specific
     subdirectories, or carve out ones that shouldn't be crawled),
     `needs_product`/`account_required` (if the skills assume a specific
     paid/first-party product).

   - **Any other git host (GitLab, self-hosted, Gitea, Bitbucket, ...)**
     → `git_repos:` (services/ecosystem/import_adapters/git_repo.py — no
     host-specific API needed, just a plain `https://` clone URL):
     ```yaml
     - url: https://gitlab.com/someone/their-skills-repo.git
       ref: main                      # branch/tag/commit — defaults to HEAD if omitted
       category: engineering
       tags: [whatever, fits]
       tos_note: "Public GitLab repo, MIT (repo-root LICENSE)."
     ```
     `url` **must** be `https://` — anything else fails the whole file's
     load, loudly, before any crawl runs. Same optional
     `include_paths`/`exclude_paths`/`needs_product`/`account_required`
     fields as `github_repos`. If the host requires a read token, set
     `read_token_env: SOME_ENV_VAR_NAME` — the *name* of an environment
     variable that holds the token (never the token itself in this
     file); the crawl/install processes read it from their own
     environment at the time they actually need it.

   - **A `.well-known/agent-skills` or `.well-known/skills` publisher**
     → `well_known_sites:` (see the existing `supabase.com` entry for
     the shape).

   - **A single hand-picked MCP server repo** → `mcp_server_repos:`.

   - **An Activepieces community piece** → `activepieces:` (check that
     specific piece's own API Terms of Service — see the many per-piece
     `tos_note` entries already there for the level of detail expected;
     note `slack` is explicitly barred, see that entry's own note on why).

5. **Use a real taxonomy category.** `category:` must be one of
   `services/ecosystem/config_service.py`'s `TAXONOMY_CATEGORIES` — a
   category that isn't in that list makes every item from this source
   silently invisible in Discover (a real incident this file's loader
   now catches at load time: `load_sources()` raises `ValueError`
   immediately, naming the offending source, rather than letting a bad
   category ship silently).

6. **Write a real `tos_note`.** Not a formality — every existing entry
   states *why* this source is safe to crawl on an ongoing, automated
   basis (public/no-auth-required, individual maintainer vs. a vendor
   with restrictive API terms, any account/product dependency). If the
   source has published API Terms of Service, check them for anything
   that would bar this kind of automated, unattended crawling (see the
   `activepieces:` block's per-piece notes, and the `slack` exclusion,
   for what a real finding looks like either way).

7. **Open a PR.** The crawl workflow itself never edits this file — every
   change goes through normal review. Once merged, the next scheduled
   (or manually dispatched) crawl run picks it up automatically; nothing
   else needs to happen.

## Running a crawl to test a new source

The crawl workflow (`.github/workflows/ecosystem-catalog-crawl.yml`) is
currently `workflow_dispatch`-only (see that file's own comment on why) —
trigger it manually from the Actions tab, or run the same script it does,
locally, against your own `docs/ecosystem/catalog/` copy:

```
python -m scripts.ecosystem.run_catalog_crawl \
  --sources docs/ecosystem/catalog/sources.yaml \
  --yanked docs/ecosystem/catalog/yanked.yaml \
  --output-dir /tmp/catalog-crawl-test
```

Check the printed crawl report for your new source's included/excluded
counts and reasons before opening the PR that adds it for real.

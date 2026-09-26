# LLD — External import (`github_repo` / `well_known`)

**Purpose**: `create_via: import` (task B-6's third payload shape, previously a license-precheck-only stub) fetching a skill from a public GitHub repository or a domain's own published skill index, and running it through the exact same gate/install pipeline as `write`/`upload`. Task I, landed pre-M3.

## Files / functions
- `services/ecosystem/import_adapters/github_repo.py` — `import_from_github(repo, ref=None)`. `repo` is `"owner/repo"`; `ref` a branch/tag/sha, or `None` for the default branch's HEAD.
- `services/ecosystem/import_adapters/well_known.py` — `import_from_well_known(domain, skill_slug)`.
- `services/ecosystem/import_adapters/ssrf_guard.py` — `assert_safe_https_url(url)`: https-only, fresh DNS resolution on every call (no cached-result trust, closing the DNS-rebinding gap), rejects if any resolved address is private/loopback/link-local/multicast/reserved. New code — no existing SSRF (private-IP-blocking) validator was found anywhere in this codebase to reuse (searched `core/`, `connectors/`, `agents/` first). `connectors/net_relay.py`'s `relay_request()` **is** reused, for the actual HTTP transport — it's a real, existing "outbound guard" pattern, but an egress-topology relay (routes through `LLM_PROXY_URL` when the host has no direct internet access), not an SSRF validator; both concerns are needed and are cleanly separable.
- `services/ecosystem/import_adapters/fetch_cache.py` — `get_cached(identity)`/`put_cached(identity, content)`: Redis-backed (`RDB_CACHE`, 24h TTL — matches `idempotency_service.py`'s own TTL convention), storing an `ecosystem_object_storage` object_key per fetch identity so a repeat import of the same exact commit/digest never re-fetches over the network.
- `services/ecosystem/import_adapters/github_credential.py` — `auth_headers()`/`configure_github_access_hint()`: the ONE instance-level credential (`GITHUB_IMPORT_TOKEN` env var — a fine-grained, read-only PAT), never a per-user token this phase. Falls back to anonymous GitHub API access (60 req/hr) with a hint surfaced when no token is configured.
- `services/ecosystem/items_service.py`'s `get_or_create_import_source()` — one `ecosystem_sources` row per distinct `(kind, url)`, instance-wide (`org_id=None`, unlike `get_or_create_local_source()`'s deliberately per-org row), recording `tos_checked_at`/`tos_notes` on first import from that exact location.
- `services/ecosystem/create_service.py`'s `create_via_import()` — dispatches on `kind`; `github_repo`/`well_known` use their adapter's own discovered license (the caller-supplied `license` param is unused for these two); every other `kind` value keeps the original B-6 scope (pre-check against the caller-declared license, then `NotImplementedError` — disclosed, not silently faked). `_create_item_and_version()` gained an optional `source_id`/`attribution` parameter so import can point the item at the real external source row and record provenance (`EcosystemItemVersion.attribution`, e.g. `"github_repo:acme/hello@<sha>"`) instead of the write/upload path's per-org local source.
- `routers/ecosystem_router.py` — `POST /ecosystem/items {create_via:"import", kind, ref}` (same endpoint as `write`, dispatched by `create_via`); `_handle_ecosystem_error()` maps `ImportRateLimitedError`→429 (with `retry_after`) and `ImportFetchError`→502.
- `services/ecosystem/errors.py` — `ImportFetchError`, `ImportRateLimitedError`.

## API and DB changes
No new tables. Uses `ecosystem_sources` exactly as designed in `ECOSYSTEM_PLAN.md` §4/§7 (the `kind`/`secret_backend`/`tos_checked_at` columns existed since M1 but had no writer for `github_repo`/`well_known` until this task).

## Sequence diagrams
```
POST /ecosystem/items {create_via:"import", kind:"github_repo", ref:"owner/repo[@ref]"}
    → import_from_github(owner/repo, ref)
        → GET /repos/{owner}/{repo}                       -- repo SPDX license check (BEFORE any further fetch)
        → GET /repos/{owner}/{repo}/commits/{ref|default}  -- resolve to an exact commit sha ("pin commit SHA")
        → fetch_cache hit? use cached bytes : GET /repos/{owner}/{repo}/contents/SKILL.md?ref={sha}, then cache it
        → parse SKILL.md frontmatter -> its own license: field checked independently (BOTH must pass)
    → get_or_create_import_source("github_repo", "https://github.com/{owner}/{repo}", ...)  -- ToS recorded once
    → _create_item_and_version(..., source_id=<that row>, attribution="github_repo:{owner}/{repo}@{sha}")
        → same tail every creation path shares: publisher resolve, version row (content-hash idempotent),
          enqueue_gate_run() -> ecosystem_gate_queue -> gate-worker -> full 7-stage gate, exactly like write/upload

POST /ecosystem/items {create_via:"import", kind:"well_known", ref:"domain/skill_slug"}
    → import_from_well_known(domain, skill_slug)
        → GET https://{domain}/.well-known/agent-skills/index.json (fallback: /.well-known/skills/index.json)
        → find entry by slug -> its license: field checked
        → fetch_cache hit? use cached bytes : GET entry.download_url, then cache it
        → verify sha256(downloaded bytes) == entry.sha256 -- hard failure on mismatch, every fetch, cached or not
    → get_or_create_import_source("well_known", "https://{domain}", ...)
    → _create_item_and_version(..., attribution="well_known:{domain}/{skill_slug}#{sha256}")
```

## Edge cases and errors
- **Two independent license checks for `github_repo`, both must pass**: the repo's own detected SPDX license (GitHub's license-detection API) AND the SKILL.md's own `license:` frontmatter field. A permissively-licensed repo can still bundle a differently-licensed individual file — checking only one would miss that. Verified by `test_skill_md_own_license_field_also_checked` (repo=MIT, SKILL.md=GPL → blocked).
- **The repo-level check happens before ANY other GitHub API call** — `test_repo_level_gpl_license_blocks_before_any_content_fetch` asserts exactly one HTTP call was made when the repo license already fails.
- **Rate limiting**: a GitHub `403`/`429` response raises `ImportRateLimitedError` with `retry_after` parsed from the response's own `Retry-After` header when present, plus `github_credential.configure_github_access_hint()`'s message when no token is configured — surfaced to the router as `429` with a `retry_after` field, not a generic failure.
- **sha256 mismatch (`well_known`) is always a hard failure**, verified on every fetch — cached or freshly downloaded — never downgraded to a warning, since it means either the index or the content itself was tampered with or is simply wrong.
- **DNS-rebinding**: `assert_safe_https_url()` re-resolves DNS on every call rather than trusting a previously-validated result, so a hostname that resolves to a public address at check time and a private one moments later at fetch time (a classic SSRF bypass) is still caught — both adapters call it immediately before every actual HTTP request, not once per import.
- **Disclosed scope limitation**: `github_repo` fetches `SKILL.md` only, not a directory of bundled scripts/references (unlike the `upload` payload shape, which supports a small bundle). Extending to a full directory tree is future work.
- **`well_known`'s index schema (schema_version "0.2.0") is this implementation's own documented interpretation** — no external spec document was available to verify against when this was built; see the module's own header comment. Treat it as a clearly-scoped first pass, not a claim of byte-for-byte compliance with some external standard.
- **Fetch cache is Redis-backed with a 24h TTL and persists across process restarts** (unlike the ecosystem test suite's Postgres tables, which a shared `conftest.py` fixture truncates every test) — a test asserting "fetches exactly once across two imports" must use a fresh, unique fetch identity per test run, or it will spuriously pass/fail depending on leftover state from a previous run. Hit this directly while writing `test_repeat_import_of_same_sha_uses_cache_not_a_second_fetch` — fixed by generating a random repo/sha per test invocation.
- **A leaked, unclosed `SessionLocal()` in a test blocked every subsequent test's TRUNCATE for minutes** (a real incident during this task's own testing): a test that inlined `SessionLocal().query(...).first()` without ever closing that session left an open transaction holding a lock on `ecosystem_installs`, and the next test's shared-conftest `TRUNCATE ... CASCADE` blocked on it until the DB's statement timeout fired (30-400+ seconds observed, not a hang forever, but effectively so for a test suite). Every DB-touching test in this codebase must open/close its own `SessionLocal()` in an explicit `try/finally`, never inline.

## Flags
None new. `ECOSYSTEM_TYPE_SKILL` (already on) gates skill creation generally; import is not separately flagged.

## Tests
`tests/services/ecosystem/import_adapters/` (26 tests: `test_ssrf_guard.py` 8, `test_fetch_cache.py` 3, `test_github_repo.py` 8, `test_well_known.py` 7) — all against fabricated/recorded HTTP fixtures (`connectors.net_relay.relay_request` monkeypatched), no live network. `tests/services/ecosystem/test_create_service.py` — 4 new tests wiring `create_via_import()` end-to-end against a real Postgres instance (item+version+gate-run created, auto-installed, `LicenseNotAllowedError` propagated, two imports from the same repo share one `ecosystem_sources` row), with the adapter's own `import_from_*()` function mocked at that layer (the HTTP-fixture tests already cover the adapter internals — no need to re-mock HTTP at this layer too).

## How to extend
The MCP Registry and skills.sh-via-GitHub adapters (deferred to the MCP phase, `ECOSYSTEM_PLAN.md` §7's extended notes) should follow this file's exact shape: a `services/ecosystem/import_adapters/<kind>.py` module exposing one `import_from_<kind>(...)` function returning the same `{"manifest", "files", "license", "display_name", "description", "resolved_sha", "source_url"}` dict shape, reusing `ssrf_guard`/`fetch_cache` as-is, and one new `if kind == "<kind>":` branch in `create_via_import()`.

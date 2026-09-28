# External Sources — Live Marketplace Catalog (Design, superseding the earlier proposal)

**Status: APPROVED — implementation in progress on `feature/ecosystem-external-sources`.** This supersedes the "separate catalog repo" proposal below §0 entirely (kept only as historical context — the actual design is a branch of *this* repo, not a new one). No ainxt-operated server exists anywhere in this design; no telemetry, no data collected, no call to any ainxt-operated service. Standing rules from the whole ecosystem initiative apply unchanged: MIT/Apache-2.0 only, additive-only to non-ecosystem files (listed with file:line + reason wherever one is touched), no AI-tool/vendor names anywhere, new flags default OFF.

---

## 0. What changed from the original proposal

The original proposal (this section's predecessor, still below as history) assumed a *separate* GitHub repo for the catalog, published as a signed release asset. The approved design instead keeps the catalog **inside this same repo**, on an orphan branch (`ecosystem-index`) with no shared history with `main` — no second repo to create, secure, or hand off; branch protection and the existing repo's own CI identity cover signing. Everything else (signed index, pinned SHAs, sync worker, admin Sources screen, strict Tier-1 licensing) carries forward, adjusted to this shape.

---

## 1. Catalog structure — orphan branch, not a new repo

- **`ecosystem-index` branch**: created via `git checkout --orphan ecosystem-index` from an empty tree — genuinely no shared history with `main`, so a shallow clone of it never pulls any application source. Contains only:
  - `sources.yaml` — the crawl allowlist (§3).
  - `catalog/<item_type>/<publisher>/<name>.yaml` — one pointer file per catalog entry.
  - `yanked.yaml` — namespaces removed from the catalog (§7).
  - `index.json` (sharded by item type once large — `index/skill.json`, `index/mcp_server.json`, etc.) — the built, served artifact.
  - `index.json.sig` (or per-shard `.sig` files) — the detached signature (§2).
  - A `README.md` explaining this branch's purpose and how to squash its history later (its commit history grows with every crawl; squashing periodically is an ops action, not something the workflow does automatically).
- **No skill file bytes ever land on this branch.** A pointer entry references the *source's own* repo/URL at a pinned commit SHA (or content digest for well-known sites) — installing fetches from there, at install time, through the exact same adapters the starter-catalog import already uses (§8).
- **Pointer entry fields** (one YAML file per entry, `catalog/<item_type>/<publisher>/<name>.yaml`):
  ```yaml
  namespace: publisher/name
  item_type: skill            # skill | mcp_server (mcp hidden in UI until MCP ships)
  display_name: "..."
  description: "..."           # short, index-level
  category: engineering
  tags: [code-review, ...]
  source:
    kind: github_repo | well_known | mcp_registry
    url: https://github.com/owner/repo
    path: skills/foo           # subdirectory, if any
    ref: <pinned commit SHA>   # or digest for well_known/mcp_registry
  license:
    spdx: MIT
    evidence: "SKILL.md license field"   # or "repo-root LICENSE", "folder LICENSE", etc.
  compatibility: chat | tool_dependent
  content_hash: sha256:...
  attribution: "adapted from ... (MIT)" # or empty
  crawled_at: "2026-...T...Z"
  ```
  Kept deliberately flat and small — 10k+ entries must stay a few MB total. `index.json` is the same data flattened into one array (or per-type shards) for fast client-side fetch; the individual YAML files are the source of truth a PR reviews, `index.json` is generated from them.
- **One workflow, on `main`** (`.github/workflows/ecosystem-catalog-crawl.yml`): scheduled (e.g. daily) + `workflow_dispatch` (manual trigger). Checks out `ecosystem-index` (not `main`'s own tree), runs the crawler (§3-4, code lives on `main` under `services/ecosystem/catalog_crawler/`, imported by a small script the workflow calls), rebuilds `index.json`, signs it (§2), commits the result back to `ecosystem-index` with a bot identity. Bot permissions: `contents: write` scoped to that one branch only (branch protection on `ecosystem-index` should still require the workflow's own token, not arbitrary pushes — document in §9). Routine crawl commits (new commits picked up, re-checks, no `sources.yaml` change) can auto-merge/auto-commit directly since nothing human-reviewed changed; a `sources.yaml` change itself always goes through a normal reviewed PR (§7) — the workflow never modifies `sources.yaml` itself.

## 2. Signing

**Decision: Sigstore keyless signing via the workflow's own GitHub Actions OIDC identity** (the `sigstore-python`/`cosign` toolchain — Apache-2.0 — rather than minisign, which would require managing and rotating a long-lived private key ourselves for no real benefit here, since GitHub Actions' OIDC-backed keyless flow already gives a verifiable, non-repudiable signer identity tied to *this exact workflow file in this exact repo* with zero key-management burden). The workflow signs `index.json` (or each shard) producing a Sigstore bundle (`index.json.sigstore` — includes the signature, the short-lived cert, and the Rekor transparency-log inclusion proof) committed alongside it on `ecosystem-index`.

**Verification (installation side)**: a configured **trusted signer** (`services/ecosystem/catalog_crawler/signing.py`'s `TrustedSigner`) — the expected OIDC issuer + the GitHub Actions workflow's own repo + its declared `name:`, deliberately **not** the branch ref (review decision, 2026-09-28: a ref-based match would break every time the workflow moves branches, e.g. a fork's temporary default-branch switch for validation, or the eventual move from a feature branch to `main`, even though it's provably the same workflow file in the same repo) — defaults to the upstream repo's own identity; **a fork must set its own** (`ECOSYSTEM_CATALOG_TRUSTED_SIGNER`, a JSON string `{"issuer": "...", "repository": "owner/repo", "workflow_name": "..."}`, or the sync worker refuses to trust anything, fail-closed) since a fork's crawl runs under the fork's own OIDC identity, not upstream's. Verified via three separate X.509v3 certificate extensions Fulcio embeds (`sigstore.verify.policy`'s `OIDCIssuer`/`GitHubWorkflowRepository`/`GitHubWorkflowName`), combined with `AllOf` — not the single-SAN `Identity` policy, which only supports an exact-string match and would need the ref baked in. The crawl workflow itself also self-verifies immediately after signing (`--verify-after-sign`), using a signer value built from its own ambient `github.repository`/`github.workflow` context — never hard-coded, so it can never drift from the repo/workflow actually running the job — and fails the job (nothing gets committed) if that self-check doesn't pass. Verification is real cryptographic signature + Rekor-log verification (`sigstore-python`'s verifier library), never a "trust whatever's there" fallback.

**Offline by default, real requirement (air-gapped/firewalled installs, offline snapshot import)**: verification loads Sigstore's public trust root (Fulcio/Rekor/CT keys) from a pinned, checked-in file (`services/ecosystem/catalog_crawler/vendor/sigstore_trusted_root.json`, fetched once via a real TUF refresh and vendored, not regenerated at runtime) via `TrustedRoot.from_file()`, and verifies the bundle's own embedded Rekor inclusion proof against it — confirmed directly against `sigstore-python`'s own verification code path that this makes **zero network calls** (its `RekorClient` is constructed but never invoked when the bundle carries an embedded inclusion proof, which every bundle this workflow produces does). An explicit `allow_online_trust_root_refresh=True` opt-in instead fetches a fresh trust root from `tuf-repo-cdn.sigstore.dev` — for staying current with an eventual Fulcio/Rekor key rotation — but is never the default and never required for a normal sync or offline-snapshot import. Signing itself (CI-side only) is inherently online regardless: it needs `fulcio.sigstore.dev` (certificate issuance), `rekor.sigstore.dev` (log submission), and `token.actions.githubusercontent.com` (the ambient OIDC token) — see §9 for the full egress breakdown by mode.

## 3. Sources the crawler uses

Reusing the *existing, already-shipped* adapters — never a second implementation:

| Source kind | Adapter reused | Notes |
|---|---|---|
| GitHub repositories | `services/ecosystem/import_adapters/github_repo.py` (`discover_skills_in_repo`, subdirectory `SKILL.md` discovery, already built for the starter catalog) | Crawl allowlist = approved repo list (§4, seeded from `docs/ecosystem/catalog/starter-approved.md`) + GitHub topic search (`topic:agent-skills`, anonymous, rate-limited) for discovery of *new* candidate repos — topic-search results are proposals for a human to add to `sources.yaml` via PR, never auto-added. |
| Well-known sites | `services/ecosystem/import_adapters/well_known.py` (discovery schema 0.2.0 + legacy fallback, digest verified over served bytes — already rewritten against the real standard this session) | Admin-approved domain list only (§9's Sources screen), same as GitHub's reviewed allowlist. |
| skills.sh-listed skills | Via GitHub only | skills.sh is discovery-only — a human (or the crawler's own reporting) notes "skills.sh lists this GitHub repo," the actual fetch is always the GitHub adapter against that repo directly. No skills.sh API call anywhere in this codebase. |
| Official MCP Registry | New adapter, `services/ecosystem/import_adapters/mcp_registry.py` | `https://registry.modelcontextprotocol.io`, API v0.1. Crawled and stored as real MCP pointer entries in the catalog (`item_type: mcp_server`) — **hidden in the UI** while the MCP item type itself is `coming_soon` (existing `ECOSYSTEM_TYPE_MCP` flag), so the data exists and is ready the moment that phase ships, without a second crawl needed then. |
| Excluded, explicitly | — | ClawHub (any form); aggregator/"awesome" lists as a *source* (discovery-only, same as skills.sh — never fetched from directly); AI-vendor skill packs; the reference-design project's own bundled skills. No vendor marketplace URL as a default anywhere in code. A generic "plugin marketplace manifest" source type is out of scope for this phase (belongs to the future Plugins phase). |

Every source in `sources.yaml` carries a recorded ToS note (`tos_note:` field) — mirrors the existing `ecosystem_sources.tos_checked_at` schema field.

**GitHub API rate-limit efficiency (found live, 2026-09-28)**: a rehearsal crawl exhausted GitHub's unauthenticated 60-req/hour budget almost immediately — not because a configured `GITHUB_IMPORT_TOKEN` was somehow insufficient (none was ever configured in that run), but because the adapter's own call pattern was wasteful regardless of a token being present: one Contents-API call per file, plus a full repo/commit/tree re-fetch on every import that had just fetched the same three things moments earlier during discovery. Fixed: file content now comes from `raw.githubusercontent.com` (§9 — not subject to the REST API's rate limit at all), every `api.github.com` metadata call is ETag-cached (a 304 response is documented by GitHub to not count against the rate limit either), and the crawler checks a repo's current HEAD (one lightweight, ETag-cacheable call) against the previous crawl's own recorded commit before doing any per-skill work at all — an unchanged repo is skipped entirely, reusing its previous entries verbatim. Every crawl logs how many API calls it actually used (`CrawlReport.api_call_stats`).

## 4. Licensing — Tier 1, strict, no exceptions (unchanged from the original proposal's §7, restated)

**Applies to every item this pipeline ever touches, catalog and live search alike — no override anywhere in this pipeline.** Reuses the *same* license-inheritance function the starter-catalog import already uses (`services/ecosystem/import_adapters/github_repo.py`'s inheritance chain: SKILL.md's own `license:` field → nearest LICENSE file in its folder/parents → repo-root LICENSE, first clear SPDX match wins; NOASSERTION/unknown/absent → excluded) — never reimplemented, never diverged.

- **Included**: MIT or Apache-2.0 only (dual licenses allowed if MIT/Apache-2.0 is one of the options — record which was actually relied on).
- **Excluded on any conflict**: an explicit non-MIT/Apache license field anywhere in the chain, a *different* LICENSE/COPYING/NOTICE file inside the skill's own folder even if the repo root says MIT/Apache, or an other-license SPDX header found in any bundled file.
- **Provenance check**: "adapted from"/credits text must itself point at an MIT/Apache-2.0 upstream — recorded in `attribution`.
- **MCP entries**: license comes from the package's own npm/PyPI metadata; an OCI-packaged server is only included with an explicit MIT/Apache licenses label; a remote-only server (no installable package at all) is listed only after a recorded ToS review and is marked `"remote service"` in its pointer entry so the UI can disclose that distinction.
- **Attribution stored per entry**: copyright notice + license text (and the Apache-2.0 NOTICE file's content, if present) — shown on the item's Detail page License tab at install time, not just crawl-time metadata.
- **Fast safety checks at crawl time** (structure sanity, obvious secrets, hidden/injected instructions) reuse the same lightweight checks `static_safety_stage.py` already runs — catches an obviously bad candidate before it's even offered in Discover. **The full 7-stage gate still runs on every actual install**, unconditionally — crawl-time checks are a pre-filter, never a substitute.
- **Item-level neutrality check, at crawl time**: a skill's own content (manifest + bundled files) is scanned for specific AI product/vendor names (`services/ecosystem/catalog_crawler/neutrality_check.py`) — content that names one is excluded, same rule the starter-catalog scan already applied by hand (one candidate was excluded from that batch for extensively naming AI products/vendors). Heuristic and disclosed as such, same class of tradeoff as the fast-safety injection-pattern scanner; excluded items are logged with which name(s) matched, never silently dropped.
- **Per-repo `include_paths`/`exclude_paths` in `sources.yaml`**: scopes a crawl to specific subdirectories, and/or excludes specific subtrees even from an otherwise-included repo — e.g. a subtree flagged for a copyright/originality concern the automated gate doesn't check (it checks license grants and safety, not whether prose was copied from an uncredited template).
- **Cross-source content-hash dedup**: the same skill can legitimately be reachable from more than one configured source (a GitHub repo and a well-known site mirroring it). Exactly one copy is kept, preferring the GitHub-repo entry (pinned commit SHA) over a well-known entry over an MCP registry entry for identical content — the loser is logged as excluded ("duplicate content"), not silently dropped without a reason.
- **`needs_product`/`account_required` tags**: a `sources.yaml` entry can declare the product a skill needs (becomes a `needs-<product>` tag) and whether using it for real needs an account (`account-required` tag) — surfaced alongside, not instead of, the compatibility tag (chat vs. tool-dependent is a different axis than "needs ClickHouse").
- **Crawl limits, reported not silently enforced**: `sources.yaml`'s `crawl_limits` (`max_skills_per_repo`, `max_total_items`) caps how large a single crawl can grow the catalog. Exceeding either is recorded in the crawl report's "Over cap" section — available vs. included counts — never a silent truncation a maintainer would have no way to notice.
- **Anomaly circuit breaker, per source**: if more than 20% of a source's previously-crawled items changed content since the last crawl, that source's results are discarded for this run entirely (reported as a circuit-breaker trip) rather than trusted — a source suddenly replacing most of its content is treated as a possible compromise/hijack. A no-op on a first crawl (nothing to compare against yet).
- **Exclusions are logged, never listed**: every rejected candidate goes into the crawl report (§ stop point 2) with its specific exclusion reason — never silently dropped, never shown to a user.

## 5. Instance-side catalog sync — LANDED (2026-09-28)

`services/ecosystem/catalog_sync.py`, wired into `workers/start_workers.py`'s existing cron-thread `interval_jobs` list (the plain scheduler thread, not an RQ-forking worker — safe per the gate-worker/gate-sweeper fork-lock lesson), gated behind `ECOSYSTEM_CATALOG_SYNC`:

- **Catalog URL is configurable** (`ECOSYSTEM_CATALOG_URL`) — the base `index/` directory URL (e.g. `https://raw.githubusercontent.com/<org>/<repo>/ecosystem-index/index`), **not** a specific shard file; `sync_catalog()` appends `/skill.json`/`/mcp_server.json` and their `.sigstore` siblings itself. Pointing at a fork for testing means setting this one env var (plus its own `ECOSYSTEM_CATALOG_TRUSTED_SIGNER`), nothing else.
- **ETag/If-None-Match** on every fetch (`fetch_cache.py`'s existing content-by-identity cache, same convention as `github_repo.py`'s `_github_get()`) — a 304 skips that shard's verify/upsert entirely.
- **Signature verification** against `ECOSYSTEM_CATALOG_TRUSTED_SIGNER` (§2's `TrustedSigner`) before trusting anything in the fetched index — fail-closed: a missing/invalid bundle or a failed `verify_index_bytes()` call aborts THAT shard (recorded on `ShardSyncResult.error`), upserting nothing from it; the other shard still syncs independently.
- **Idempotent upsert**: each pointer entry becomes (or updates) an `EcosystemItem` row with `scope="central_index"` — no skill content is ever downloaded at sync time, only the pointer metadata (stashed on the new `catalog_pointer` JSONB column for install-time use). Anything previously synced under a shard's item_type but absent from the current fetch (removed upstream, including anything the crawler dropped via `yanked.yaml`) is marked `status="yanked"` (hidden from Discover, not deleted — audit/install history is preserved).
- **`item_type="mcp_server"` is stored with `status="coming_soon"`**, excluded from Discover's default listing (`items_service.list_items()`'s own status exclusion, additive) until an MCP installer exists (`create_via_import`'s `mcp_registry` branch still raises `NotImplementedError` by design) — "stored, not shown," exactly per spec.
- **Offline snapshot**: `sync_from_local_files()` does the same verify+upsert from local file paths instead of HTTP — the underlying function exists and is tested; no admin-upload UI for it yet (disclosed gap, see below).
- **Admin "Sync now"**: `POST /ecosystem/admin/catalog-sync` (gated by `marketplace:admin_sources`, same permission the other admin-Sources endpoints already use) runs `sync_catalog()` synchronously and returns its real report — this is where "reject unsigned/invalid, clear error" actually surfaces today. **No dedicated admin Sources frontend screen exists yet** — disclosed gap; this endpoint is what that screen will call once it exists.
- **Discover shows `skill`-type catalog items by default** the moment `ECOSYSTEM_CATALOG_SYNC` syncs them in — `items_service.list_items()`'s existing `scope.in_((..., "central_index"))` filter and `_item_to_summary()`'s tolerance for "no version yet" already supported this with zero read-path changes; **nothing auto-installed** by the sync itself. `ECOSYSTEM_LIVE_SOURCES` (a separate, still-unbuilt "from the web" live-search section) is defined as a flag but has no behavior wired to it yet — also disclosed, not in this round's scope.

## 6. Install-from-catalog — LANDED (2026-09-28)

`services/ecosystem/catalog_sync.py`'s `materialize_from_catalog(item_id, requested_by, org_id)`, called from `POST /ecosystem/items/{id}/install` when the request omits `version_id` (only valid for a `scope="central_index"` item with no version yet — every other item still requires it). Fetches the ONE chosen skill from its *original* source at the pointer's pinned ref/path (github_repo/well_known only — never from `ecosystem-index` itself, which holds no skill bytes) by reusing the existing `create_service.py` import adapters directly (`import_from_github`/`import_from_github_path`/`import_from_well_known` — no second implementation). Steps: fetch → recompute the content hash over the fetched manifest+files (`pointer_schema.compute_content_hash()`, the same function the crawler itself uses) and compare against the pointer's recorded `content_hash` — a mismatch raises `CatalogContentDriftError` rather than installing content that no longer matches what was indexed → **re-check license against the live content** (the import adapter's own Tier-1 pre-check, unchanged) → `versions_service.create_version_for_content()` + `gate_service.enqueue_gate_run(trigger="ui_add", ...)` — the full 7-stage gate, exactly like a direct import today, including its existing auto-install-on-pass behavior (so the router's own explicit `install()` call right after is a no-op/`ConflictError`-caught fallback in the common private-install case, not a second real install). `mcp_registry`-sourced pointers raise `CatalogInstallNotSupportedError` (matches their `status="coming_soon"` — no installer exists yet). **Not yet built this round** (real future work, not contradicted by anything landed here): a *bulk* "install N catalog items" action queued within the existing gate concurrency limit (the fork-lock-fix round's own `--gate --n 2` setting already caps concurrency for any caller, but nothing yet drives a bulk catalog-install flow through it); and marking an already-installed catalog copy "source unavailable" if its origin later becomes unreachable (today it just keeps working, unverified, with no forced uninstall — no worse than before, just not yet actively detected).

## 7. Curation and maintenance

- **`sources.yaml` changes require a reviewed, maintainer-approved PR.** Routine crawl output (new commits picked up for already-approved sources, re-checks with no allowlist change) may auto-commit/auto-merge on `ecosystem-index` once its own checks pass (license re-verification, digest computation) — the crawl workflow never edits `sources.yaml` itself, only the generated `catalog/*.yaml` + `index.json` + signature.
- **`yanked.yaml`**: a flat list of namespaces to remove from the *catalog* (distinct from `policy_service.py`'s existing per-install yank/force-disable, which still applies independently to already-installed copies). Editing it is also a normal reviewed PR.
- **Forks and scheduled crawls**: the crawl workflow's scheduled trigger **must not run in a fork** unless the fork owner explicitly re-enables it (GitHub disables scheduled workflows on forks by default — this design relies on that default, not a custom guard, and documents it explicitly rather than fighting it). A fork wanting its own live catalog: (1) re-enable the scheduled workflow (or trigger it manually) in the fork's own Actions settings, (2) the workflow runs under the fork's own OIDC identity automatically — no code change needed, (3) set `ECOSYSTEM_CATALOG_TRUSTED_IDENTITY` on any installation that should trust *that fork's* index instead of upstream's, (4) point `ECOSYSTEM_CATALOG_URL` at the fork's own `ecosystem-index` branch raw URL.

## 8. Org-specific sources + admin Sources screen

A new admin surface (`packages/ecosystem-ui/src/components/admin/AdminSources.tsx`, alongside the existing `AdminPolicies.tsx`/`AdminGateFindings.tsx`):
- Catalog URL (editable, admin-only), sync status + last-sync time/result.
- Enable/disable live search independently of catalog sync.
- Approved well-known sites list (admin-managed).
- **Org-specific sources** (a company's own internal GitHub org, an intranet well-known site) — added here directly, going through the *same* license rules and full gate as any public-catalog item, just scoped to that org only. May also be **bootstrapped at deploy time** from an env var or an `ecosystem.yaml` deploy-time config file into the DB on first boot, then managed normally in the UI afterward (deploy-time seeding, not a permanent config-file source of truth).
- GitHub credential status (reuses the existing `GITHUB_IMPORT_TOKEN`-style credential plumbing).
- Crawl/sync error surfacing — an admin sees *why* the last sync found nothing new or rejected candidates, not just silence.
- **Documented egress host list** (§9) so a network-restricted deployment knows exactly what to allowlist.

## 9. Egress hosts

Confirmed against the actual, landed code (crawler + adapters + signing), by mode. No ainxt-operated host anywhere in this list, ever.

| Mode | Hosts contacted |
|---|---|
| Crawl (GitHub repos) — metadata only (repo/commit/tree, ETag-cached) | `api.github.com` |
| Crawl (GitHub repos) — file content (SKILL.md, bundle files, conflict-scan files) | `raw.githubusercontent.com` — not the Contents API, and not subject to the REST API's rate limit at all (rate-limit efficiency review, 2026-09-28) |
| Crawl (well-known sites) | whatever domain is listed in `sources.yaml`'s `well_known_sites` (admin/maintainer-approved only) |
| Crawl (MCP Registry) | `registry.modelcontextprotocol.io`, `registry.npmjs.org` (npm license lookup), `pypi.org` (PyPI license lookup) |
| Skill/archive content fetch (either crawl or install-from-catalog) | `objects.githubusercontent.com` (GitHub release-asset redirects), plus the specific repo/site host already listed above |
| Signing (CI only) | `fulcio.sigstore.dev` (certificate issuance), `rekor.sigstore.dev` (transparency-log submission), `token.actions.githubusercontent.com` (ambient OIDC token) |
| Verification, default (offline) | none — loads the vendored, checked-in trust root; makes no network call at all (§2) |
| Verification, `allow_online_trust_root_refresh=True` (opt-in only) | `tuf-repo-cdn.sigstore.dev` |
| Catalog sync (not yet built, §5) | the configured `ECOSYSTEM_CATALOG_URL` host only |
| Live search (not yet built, §10) | `api.github.com`, plus admin-approved well-known sites |

## 10. Live search ("From the web")

An optional Discover section, gated behind `ECOSYSTEM_LIVE_SOURCES` (independent of `ECOSYSTEM_CATALOG_SYNC` — an instance can have one, both, or neither on): server-side queries against GitHub topic search (anonymous-rate-limited) and code search (only when the admin has configured an instance-level GitHub credential — never a per-user token for this), plus admin-approved well-known sites. Results cached briefly (short TTL, avoids hammering GitHub on every keystroke), existing rate-limit conventions applied to the outbound calls. **Only MIT/Apache-2.0 items are ever shown** — the exact same Tier-1 check, applied live, not deferred to install time. Clicking "install" from a live-search result goes through the *identical* install-from-catalog path (§6) — live search is a discovery surface, not a second import mechanism.

## 11. Flags

| Flag | Default | Effect |
|---|---|---|
| `ECOSYSTEM_CATALOG_SYNC` | `false` | Enables the instance-side sync worker + Discover's catalog-items-by-default section. |
| `ECOSYSTEM_LIVE_SOURCES` | `false` | Reserved for Discover's "From the web" live-search section (plan §10) — flag defined, no behavior wired to it yet. Independent of the flag above. |
| `ECOSYSTEM_CATALOG_URL` | `""` (empty — must be set) | The catalog's base `index/` directory URL (e.g. `.../ecosystem-index/index`), **not** a specific shard file — `catalog_sync.py` appends `/skill.json`/`/mcp_server.json` and their `.sigstore` siblings itself. |
| `ECOSYSTEM_CATALOG_TRUSTED_SIGNER` | `""` (empty — must be set) | JSON `{"issuer","repository","workflow_name"}` — who the sync worker trusts a signature from. A fork running its own catalog **must** set this to its own repo/workflow or nothing will verify. |
| `ECOSYSTEM_CATALOG_SYNC_INTERVAL_SECONDS` | `1800` | How often the scheduled sync re-fetches the catalog (also runs once ~15s after worker startup). |

The enterprise product profile (`ecosystem_product_profiles`) enables catalog sync + live search by default *when the underlying flags are on*; an admin can still disable either independently for that org via the policy/Sources screen. All users may install a catalog/live-search item into their own private space regardless; org-wide provisioning stays `marketplace:provision`-gated, unchanged from the existing install-lifecycle rules.

## 12. Reuse map (nothing here gets a second implementation)

| Concern | Shared implementation | Used by |
|---|---|---|
| GitHub fetch + subdirectory discovery | `import_adapters/github_repo.py` | Crawler, install-from-catalog, live search, the existing manual admin-import path |
| Well-known site fetch + digest verify | `import_adapters/well_known.py` | Crawler, install-from-catalog, live search |
| License inheritance chain | `github_repo.py`'s own inheritance function (SKILL.md → folder LICENSE → repo LICENSE) | Crawler (crawl-time check), install-from-catalog (re-check at install), live search (pre-filter) |
| Compatibility classification | `services/ecosystem/compatibility.py`'s `classify_compatibility()` | Crawler (stored per pointer entry), install-from-catalog |
| Object storage + admin-only import path | `store/ecosystem_object_storage.py`, `scripts/ecosystem/admin_import.py`'s hardened, container-only pattern | Install-from-catalog's actual fetch-and-store step — never a host-side script, object storage root must be the mounted volume, exactly as already enforced |
| Gate concurrency | The fork-lock-fix round's `--gate --n 2` / gate-sweeper setup | Sequential, concurrency-bounded install queue for bulk catalog installs |

## 13. Test strategy

- **Unit/fixture**: crawler logic (candidate discovery, license re-check, pointer-file generation), signing/verification (a real Sigstore bundle fixture, tampered-signature negative case), sync worker (ETag handling, digest-based idempotent upsert, offline-snapshot import), live-search filtering (non-MIT/Apache item never surfaces). Recorded fixtures throughout — **no live network calls in CI**.
- **Negative-path suite** (fail-closed, always with a clear, admin-visible reason, never a silent skip): tampered index signature; stale digest (content changed upstream, index still points at the old digest); a source disabled mid-sync; a rate-limit violation; a fork's index verified against upstream's identity (must fail — proves the trusted-identity separation actually matters).
- **End-to-end, in a fork + local setup** (this repo's own fork, `adarsh8827/ainxt-enterprise`, not upstream): run the crawl workflow for real on the orphan branch, point a local installation's `ECOSYSTEM_CATALOG_URL`/`ECOSYSTEM_CATALOG_TRUSTED_IDENTITY` at that fork's own index, confirm catalog items appear in Discover, install one end-to-end (fetch → gate → usable in chat), confirm a deliberately-non-MIT/Apache test item never appears anywhere, confirm the offline-snapshot import path works from a manually-downloaded bundle.
- **Full suite + CI baseline comparison** (0 new failures vs. `scripts/ci/known_failures.txt`), security suite, existing E2E suite — run once at the end, in the Linux container per this session's own speed-mode convention, not the Windows venv.

## Stop points (both required before proceeding past them)

1. **Before the first real crawl**: show the user `sources.yaml` — the actual repo/website/MCP Registry allowlist, with each entry's `tos_note`.
2. **After the first real crawl** (in this fork): show the crawl report — included count, excluded count broken down by exclusion reason, and a handful of sample entries with their full license evidence chain.

---

## Appendix — the original, superseded proposal (kept for history only)

*Everything below this line describes the earlier "separate catalog repo" design and is no longer the plan. Superseded by §0-13 above.*

**Status: PROPOSAL — for review. Not implemented.** Nothing here changes any behavior in the Skills phase; the starter catalog delivered alongside this document used only the already-shipped, single-shot import path (`create_via_import`, `github_repo.py`/`well_known.py` adapters, manual/admin-triggered).

A separate repo (not this one) that curates and publishes a signed index of importable items — crawl/verify/version-bump/build workflows, a detached Ed25519-style signature, published to a stable release-asset URL. An instance-side sync worker (`workers/ecosystem_sync_worker.py`) would ETag the fetch, verify the signature against a pinned public key shipped in this repo, import via the existing `create_via_import` path. Superseded because a second repo adds a real operational burden (a second CI identity to secure, a second release process, a second place branch protection has to be configured correctly) that an orphan branch of this same repo avoids entirely, while keeping every other property (signed, pinned, no skill bytes in the pointer data, reuse the existing adapters) intact.

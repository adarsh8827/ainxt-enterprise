# LLD — Data model

**Purpose**: the Postgres schema backing the Ecosystem marketplace — catalog items, versions, installs, sources, and the supporting registries (surfaces, product profiles, publishers). Landed in task B-1 (M1).

## Files / functions
- `db/migrate.py`'s `_part_ad1_ecosystem_marketplace_tables_2026_09_25()` — the migration itself. Called from `run_migrations()`. Idempotent: every statement is `CREATE ... IF NOT EXISTS` or `INSERT ... ON CONFLICT DO NOTHING`, so re-running it (e.g. on redeploy) is always a clean no-op.
- `db/models.py`'s `Ecosystem*` classes — ORM models for the tables the M1 service layer actually queries: `EcosystemPublisher`, `EcosystemSource`, `EcosystemItem`, `EcosystemItemVersion`, `EcosystemGateRun`, `EcosystemAudit`. The remaining tables the migration created (`ecosystem_installs`, `ecosystem_shares`, `ecosystem_gate_findings`, `ecosystem_reports`, `ecosystem_credentials`, `oauth_provider_configs`, `oauth_client_registrations`, `ecosystem_surfaces`, `ecosystem_product_profiles`, `ecosystem_org_products`, `credential_audit`, `desktop_devices`, `ecosystem_featured_overrides`, `ecosystem_drafts`) exist in the schema now but don't get an ORM model until the milestone that first queries them — this file's own convention (see `KnowledgeDocDeletion` for the precedent) pairs a raw-DDL `CREATE TABLE` with an ORM model added only when something needs to query it, rather than declaring every model up front.

## API and DB changes
20 new tables, all additive, none touching `skills_pg`/`skills_catalog`/`cowork_roles`/`connector_definitions`/`CredentialVault`/`user_oauth_tokens`. Full DDL: `docs/ecosystem/ECOSYSTEM_PLAN.md` §4. Two extensions enabled: `pgcrypto` (already present) and `pg_trgm` (new — backs `ecosystem_items`'s trigram search index).

Two seed tables get real rows at migration time, not left empty for a later admin step:
- `ecosystem_surfaces` — 5 rows (`chat`, `agent_studio`, `cowork`, `desktop`, `workspace_chat`).
- `ecosystem_product_profiles` — 2 rows (`enterprise`, `workspace`), matching `docs/ecosystem/CONFIG_AND_PRODUCTS.md` §3's exact feature-flag shapes.
- `ecosystem_org_products` — 1 row (`org_id='default'` → `enterprise`, `is_primary=true`) so an existing single-org deployment has a valid entitlement from day one, never landing on "no primary product" for pre-existing orgs.

`org_id` is `VARCHAR(255)` everywhere, never `UUID REFERENCES ainxt.orgs(id)` — `ainxt.orgs` doesn't exist anywhere in this codebase (verified by full-repo search); every existing multi-tenant-shaped table already uses a plain string `org_id`, and these tables follow that exact convention rather than inventing a new one.

## Sequence diagrams
_n/a for this task — this is schema, not a runtime flow. See `legacy-bridge.md` for the sequence the schema's first real consumer follows._

## Edge cases and errors
- **One `local` source per org** (`ux_ecosystem_sources_one_local_per_org`, a partial unique index on `ecosystem_sources(org_id) WHERE kind='local'`) — verified by an actual insert-a-duplicate-and-expect-failure test (`tests/db/test_ecosystem_migration.py::test_one_local_source_per_org_unique_index_enforced`), not just "the index exists."
- **Namespace uniqueness is scope-dependent**, expressed as two separate partial unique indexes rather than one plain `UNIQUE` constraint, because `org_private` items need per-org isolation (two orgs can each have their own `acme/foo`) while every other scope needs global uniqueness (`docs/ecosystem/ECOSYSTEM_PLAN.md` §4's comment above the indexes explains why a single `UNIQUE(namespace, item_type)` can't express this).
- **`ecosystem_installs`/`ecosystem_credentials`'s `UNIQUE NULLS NOT DISTINCT`** requires Postgres 15+ (this repo's CI and this milestone's test environment both use `pgvector/pgvector:pg16`) — without it, Postgres's default `NULLS DISTINCT` would silently allow duplicate org-scoped rows, since `NULL <> NULL` under the default semantics.

## Flags
None — the schema is always present once migrated; runtime behavior that reads/writes these tables is gated per-task (`ENABLE_ECOSYSTEM_MARKETPLACE`, `ECOSYSTEM_TYPE_*`, etc., all registered in task B-0).

## Tests
`tests/db/test_ecosystem_migration.py` — all 20 tables exist, both seed tables have their expected rows, and the one-local-source-per-org index actually rejects a duplicate insert (not just "exists"). Verified against a real `pgvector/pgvector:pg16` instance: migration runs clean from empty, is idempotent on a second run (no errors, no duplicate seed rows), and all 23 tests in this file pass.

## How to extend
Adding a new ecosystem table: add its DDL to `_part_ad1_...` if this is still an active migration window, or start a new dated `_part_<next-letter>1_...` function (check the tail of `db/migrate.py` for the next available label — don't guess) once M1 is closed out and a later milestone needs a schema change. Add the matching ORM model to `db/models.py` only when a service actually needs to query it, per this file's own pairing convention.

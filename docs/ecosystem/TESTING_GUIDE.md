# Ecosystem Marketplace — Manual Testing Guide

Living document, updated in the same commit as every milestone that changes tested behavior (matching `docs/ecosystem/design/CHANGELOG.md`'s own convention). Step-by-step manual checks for everything built so far — what to set up, what to call, and the expected result, including negative cases. Written for someone who has never run this feature before.

**Coverage as of this revision**: M0–M2 (create/gate/install/policy/legacy-bridge/builtin-skills) plus the pre-M3 hardening items (DB constraint repair, gate deployment separation, secret detection fix, lazy provisioning, fail-closed scanner, gate-worker health).

---

## 0. Before you start — what has a UI today, and what doesn't

**Read this first — it changes what "web" and "desktop" testing actually mean right now.**

- `ai-ui/src/components/Marketplace.jsx` is a real, existing browser UI — but it is a **separate, standalone feature that does not yet call any of the backend described in this guide**. Its data layer (`ai-ui/src/marketplaceStore.js`) is `localStorage`-backed and is explicitly scheduled for removal once a real `EcosystemClient` API adapter lands (`docs/ecosystem/CONFIG_AND_PRODUCTS.md` §11). Clicking around in that screen today exercises the placeholder, not the backend this guide tests.
- The actual backend (`services/ecosystem/`, `routers/ecosystem_router.py`) has **no browser UI wired to it yet**. Every check below uses `curl` (or any REST client) directly against the API. This is the honest, current state — not a testing shortcut.
- **Desktop vs. web vs. workspace**: nothing backend-side is surface-specific yet. `surfaces: [...]` is just a list you pass on `install`/create calls; there is no different code path per client today. The real per-surface behavior (what a desktop client vs. a workspace-layout client is actually allowed to see) is task B-11's resolver, landing at M3 — not testable before then. Treat every "surface" test below as "pass a different value in the `surfaces` array," not as "use a different physical client."
- Everything below is testable by **any authenticated user** unless marked **[Admin]** (requires the `admin` role — `marketplace:provision`/`admin_sources`/`admin_policy` permissions, `auth/rbac.py`).

---

## 1. Setup

```bash
# 1. Bring up Postgres + Redis (real, not mocked)
docker compose up -d postgres redis

# 2. Run migrations — creates all ecosystem_* tables, seeds surfaces/product profiles
python db/migrate.py
# Expect: "✓ Migration complete — no failures, required schema present."
# and, among the output, lines for Part AD1/AD2/AD3 (ecosystem tables + repair + org-exclusions table).

# 3. Turn the feature on (.env or exported before starting the gateway)
export ENABLE_ECOSYSTEM_MARKETPLACE=true
# Optional, only if you want static_safety to actually catch anything (see §3.3):
export COMPLIANCE_SERVICE_ENABLED=true

# 4. Start the gateway
uvicorn gateway:app --host 0.0.0.0 --port 8000 --reload

# 5. Start the gate-worker — REQUIRED for any created/updated item to ever
#    resolve past "verifying". Nothing gates without this running.
docker compose up -d gate-worker
#    or, running from source:
python workers/start_workers.py --gate --n 1
```

**Verify the flag actually took effect**: `curl http://localhost:8000/ainxt/v1/api/ecosystem/jobs/does-not-exist` should return `404 {"code":"NOT_FOUND", ...}`, not a 404 from FastAPI's own router-not-found page (which looks different — no JSON `code` field). If you get a bare "Not Found" with no JSON body, `ENABLE_ECOSYSTEM_MARKETPLACE` isn't set, or the gateway needs a restart to pick it up.

**Get a bearer token** (every call below needs `-H "Authorization: Bearer $TOKEN"`):
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/ainxt/v1/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"..."}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```
Use an account with the `admin` role for every **[Admin]** step; any other authenticated account for the rest.

---

## 2. Golden path: create → gate → auto-install

```bash
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "create_via": "write", "item_type": "skill",
    "namespace": "yourname/hello-skill", "display_name": "Hello Skill",
    "description": "Says hello politely.", "category": "general",
    "license": "MIT",
    "content": {"manifest": {"name": "Hello Skill", "description": "Says hello politely.", "instructions": "Always greet the user warmly before answering."}, "files": {}},
    "surfaces": ["chat"]
  }'
```
**Expected**: `202` with `{"item_id": "...", "version_id": "...", "gate_run_id": "...", "status": "verifying", "provision_scope": "private"}`.

Poll the gate run (the gate-worker from §1 step 5 must be running for this to ever change):
```bash
curl -s http://localhost:8000/ainxt/v1/api/ecosystem/jobs/<gate_run_id> -H "Authorization: Bearer $TOKEN"
```
**Expected**, within a few seconds: `{"status": "active", ..., "stuck_message": null}` — `"active"` means the gate resolved to `pass`. Then confirm the auto-install happened:
```bash
curl -s "http://localhost:8000/ainxt/v1/api/ecosystem/installs?installed_for=<your_user_id>" -H "Authorization: Bearer $TOKEN"
```
**Expected**: one row, `scope: "private"`, `origin: "created"`, `enabled: true`, pointing at the item you just created — no separate "install" call was needed.

---

## 3. Negative cases — the gate actually blocking something

### 3.1 Disallowed license (GPL) — blocked before anything else runs

```bash
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "create_via": "write", "item_type": "skill",
    "namespace": "yourname/gpl-skill", "display_name": "GPL Skill",
    "description": "d", "category": "general", "license": "GPL-3.0-only",
    "content": {"manifest": {"name": "GPL Skill", "description": "d", "instructions": "..."}, "files": {}},
    "surfaces": ["chat"]
  }'
```
**Expected**: `422 {"code": "LICENSE_NOT_ALLOWED", ...}` — rejected at the create step, before an item row is even created. Confirm nothing was created:
```bash
curl -s "http://localhost:8000/ainxt/v1/api/ecosystem/installs?installed_for=<your_user_id>" -H "Authorization: Bearer $TOKEN"
```
No new row should appear.

### 3.2 A bare AWS-key-shaped secret in the content — gate warns/fails

Same create call as §2, but set `"instructions": "access_key = \"AKIAIOSFODNN7EXAMPLE\""`. Poll the resulting `gate_run_id`.
**Expected**: with `COMPLIANCE_SERVICE_ENABLED=true` (§1 step 3), `status` resolves to `"warn"` or `"blocked"`, never `"active"`. Check `ecosystem_gate_findings` for a `static_safety` finding with `code` in `AWS_KEY`/`ENV_SECRET`.

### 3.3 The scanner being off is itself a visible, non-silent state

Restart without `COMPLIANCE_SERVICE_ENABLED` set (or `=false`) and repeat §3.2's create call.
**Expected**: the gate run resolves to `"verifying"` (verdict `pending`) **and stays there** — it must never resolve to `"active"` just because the scanner was off. This is the fail-closed fix (pre-M3 item 2 follow-up): an unscanned item can never look identical to a clean one. Confirm via `ecosystem_gate_findings`: a `static_safety` finding with `code: "SCANNER_UNAVAILABLE"`.

### 3.4 Path traversal / oversized bundle (upload path)

```bash
# A zip with a member path like "../../etc/passwd" or one declaring a huge
# uncompressed size in its header — build one with Python's zipfile module.
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/malicious.zip" -F "item_type=skill" -F "namespace=yourname/bad-zip" -F "category=general"
```
**Expected**: the traversal entry is skipped (not fatal to the rest of the upload — manifest_stage's own defense-in-depth), and a declared-size zip bomb is rejected outright before extraction. See `tests/services/ecosystem/test_create_service.py::test_create_via_upload_rejects_zip_bomb_declared_size` / `test_create_via_upload_path_traversal_entries_are_skipped_not_fatal` for the exact fixtures if you want to reproduce one.

---

## 4. Install lifecycle

Using the `install_id` from §2's install list:

| Action | Call | Expected |
|---|---|---|
| Disable | `POST /ecosystem/installs/{id}/set-enabled {"enabled": false}` | `enabled: false` |
| Re-enable | same, `{"enabled": true}` | `enabled: true` |
| Update to a newer version | `POST /ecosystem/installs/{id}/update {"version_id": "<new>"}` | `version_id` moves; old version untouched |
| Rollback | `POST /ecosystem/installs/{id}/rollback {"version_id": "<older>"}` | `version_id` moves back |
| Uninstall | `POST /ecosystem/installs/{id}/uninstall` | `204`; the item itself still exists (only your install row is gone) |

### 4.1 Required items — cannot be disabled or uninstalled by a normal user

**[Admin]** first promote an install to required (see §5.3), then as the affected user:
```bash
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/installs/<install_id>/set-enabled \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"enabled": false}'
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/installs/<install_id>/uninstall \
  -H "Authorization: Bearer $TOKEN"
```
**Expected**: both calls fail (`400`, `EcosystemError` — "is required and cannot be disabled/uninstalled"). Neither the `enabled` flag nor the row itself changes.

---

## 5. Admin actions **[Admin]**

### 5.1 Force-disable / unyank an item
```bash
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items/<item_id>/force-disable -H "Authorization: Bearer $ADMIN_TOKEN"
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items/<item_id>/unyank -H "Authorization: Bearer $ADMIN_TOKEN"
```
**Expected**: item's `status` flips to `yanked`, then back to `active`. Try force-disable as a non-admin first — expect `403`.

### 5.2 Featured overrides
```bash
curl -s -X PUT http://localhost:8000/ainxt/v1/api/ecosystem/featured/<item_id> \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"featured": true}'
```

### 5.3 Require / unrequire (promotes existing `provisioned` installs org-wide)
```bash
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items/<item_id>/require -H "Authorization: Bearer $ADMIN_TOKEN"
```
**Expected**: `{"item_id": ..., "promoted_installs": N}` — every existing `provisioned` install for that item, in that org, flips to `scope: "required"`.

### 5.4 Org-level default removal — applies to all users immediately (item 4a)

There is no HTTP route for this yet (it's a `policy_service.py` function, wired into an endpoint at a later milestone) — call it directly for now:
```python
from services.ecosystem import policy_service
policy_service.admin_disable_org_default(item_id="<item_id>", org_id="<org_id>", disabled_by="admin-user-id")
```
**Expected**: every existing install for that `(item_id, org_id)` with `origin` in `provisioned`/`required` flips `enabled: false` — check via the installs list for two different users in the same org, both should show `enabled: false` after one call, with no per-user loop needed. Then:
```python
policy_service.is_org_default_excluded(item_id="<item_id>", org_id="<org_id>")  # -> True
```
A brand-new user in that org (no install row yet) will not get this default re-provisioned once B-12's lazy-provisioning sweep lands (M3) and checks this flag — not independently testable before then.

### 5.5 Gate-worker health check

With the gate-worker running (§1 step 5):
```bash
curl -s http://localhost:8000/ainxt/v1/api/ecosystem/admin/gate-health -H "Authorization: Bearer $ADMIN_TOKEN"
```
**Expected**: `{"gate_worker_healthy": true, "last_heartbeat": "<recent ISO timestamp>", "stuck_verifying_count": 0, "message": null}`.

**Negative case** — stop the gate-worker (`docker compose stop gate-worker`), wait 90+ seconds, then repeat the same call:
**Expected**: `"gate_worker_healthy": false`, `"message"` starting with "No gate-worker has reported in...". Create a new item while the worker is stopped, wait 10+ minutes, then check that item's own job status (`GET /ecosystem/jobs/{gate_run_id}`): **expected** a non-null `stuck_message` pointing back at the admin health check, without needing admin access just to see that something is wrong.

---

## 6. Sharing and reporting

```bash
# Share your own install with another user
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items/<item_id>/share \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"shared_with_type": "user", "shared_with_id": "<other_user_id>"}'

# Report a suspect item (never permission-gated — anyone can report)
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items/<item_id>/report \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"reason": "looks suspicious"}'
```
**Expected for reporting**: after 3 reports from different reporters on the same item, every open report on that item flips to `status: "auto_hidden"` automatically — no admin action needed to trigger it.

---

## 6a. External import (task I) — `github_repo` and `well_known`

```bash
# GitHub: pins the resolved commit sha automatically. Needs a real public
# repo with a root SKILL.md carrying an MIT/Apache-2.0 `license:` field,
# in an MIT/Apache-2.0-licensed repo (GitHub's own detected SPDX license).
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "create_via": "import", "item_type": "skill",
    "namespace": "yourname/imported-skill", "category": "general",
    "kind": "github_repo", "ref": "owner/repo"
  }'
```
**Expected**: same `202 {"status": "verifying", ...}` shape as write/upload. Check the resulting version's `attribution` column (`ecosystem_item_versions.attribution`) — it should read `github_repo:owner/repo@<40-char sha>`.

**Negative case — repo/SKILL.md license mismatch**: point `ref` at a repo you know is GPL-licensed, or whose SKILL.md declares a non-MIT/Apache license. **Expected**: `422 {"code": "LICENSE_NOT_ALLOWED", ...}`, and no item was created (check `GET /ecosystem/installs` shows nothing new).

**Negative case — rate limiting**: without `GITHUB_IMPORT_TOKEN` set, make 60+ import calls within an hour. **Expected**: `429 {"code": "IMPORT_RATE_LIMITED", "retry_after": <seconds or null>}`.

```bash
# well_known: needs a real domain publishing /.well-known/agent-skills/index.json
# (or /.well-known/skills/index.json) listing a skill with a download_url + sha256.
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "create_via": "import", "item_type": "skill",
    "namespace": "yourname/well-known-skill", "category": "general",
    "kind": "well_known", "ref": "example.com/skill-slug"
  }'
```
**Negative case — sha256 mismatch**: if the domain's index and the actual downloaded file ever disagree (a stale index, a CDN serving different content), **expected**: `502 {"code": "IMPORT_FETCH_FAILED", "message": "...sha256 mismatch..."}`. Not independently reproducible without controlling the domain — covered by `tests/services/ecosystem/import_adapters/test_well_known.py::test_sha256_mismatch_is_a_hard_failure` with a fixture instead.

**Repeat-import caching**: import the same `github_repo`/`well_known` ref twice within 24h. **Expected**: the second import still creates a normal response, but no second outbound fetch happens (verified in tests via a fetch-count assertion, not something a curl-only check can directly observe — trust the automated coverage here).

## 6b. Config, capabilities, and live events (M3)

```bash
# The single call every UI makes before rendering anything marketplace-shaped.
# First call for a brand-new user also lazily provisions every builtin item.
curl -s http://localhost:8000/ainxt/v1/api/ecosystem/config -H "Authorization: Bearer $TOKEN"
```
**Expected**: the `enterprise` profile shape (CONTRACTS.md §8) — `item_types` shows `skill: available`, the other three `coming_soon`. Repeat the call as a **brand-new user who has never used the marketplace before** and check `GET /ecosystem/installs` immediately after — every builtin skill should already be installed and enabled, with no separate "Add" action taken.

**Negative case — unentitled product**:
```bash
curl -s http://localhost:8000/ainxt/v1/api/ecosystem/config -H "Authorization: Bearer $TOKEN" -H "x-ainxt-product: workspace"
```
**Expected**: `403 {"code": "POLICY_FORBIDDEN", ...}` unless your org has a `workspace` entitlement row. A product key that doesn't exist at all (`x-ainxt-product: not-a-real-product`) → `404 {"code": "NOT_FOUND", ...}`.

```bash
curl -s "http://localhost:8000/ainxt/v1/api/ecosystem/capabilities?surface=chat" -H "Authorization: Bearer $TOKEN"
```
**Expected**: `{"surface": "chat", "skills": [...], "plugins": [], "connectors": [], "mcp_tools": []}` — only skills installed, enabled, and whose `surfaces` includes `"chat"`. Disable one via `POST /ecosystem/installs/{id}/set-enabled {"enabled": false}` and re-call — it should disappear immediately (no caching delay).

**Live events**: open two terminals.
```bash
# Terminal 1 — stays open, streaming
curl -N http://localhost:8000/ainxt/v1/api/ecosystem/events/stream -H "Authorization: Bearer $TOKEN"
```
```bash
# Terminal 2 — trigger a change (install/uninstall/enable/disable/update anything)
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/installs/<install_id>/set-enabled \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"enabled": false}'
```
**Expected**: terminal 1 prints a `data: {"v":1,"type":"skill","item_id":"...","scope":"...","change":"disabled",...}` line within a second or two of the terminal-2 call, with no manual refresh. **Negative/edge case**: close terminal 1 (disconnect), fire another change, then reconnect — the disconnected event is genuinely lost (no replay); re-fetch `GET /ecosystem/installs` to see current state instead of relying on the stream to "catch up."

## 7. Legacy bridge and builtin skills (one-time / ops tasks)

```bash
# Backfill pre-existing skills_pg / AgentStudio skills into the catalog as read-only pointers
python -m scripts.ecosystem.backfill_legacy_items

# Seed the 4 first-party builtin skills through the real gate
python -m scripts.ecosystem.seed_builtin_skills
```
**Expected**: both are idempotent — running twice produces no duplicate rows (matched by `(legacy_source, legacy_ref)` or namespace). Nothing here ever writes back to `skills_pg`/`skills_catalog`.

---

## 8. DB constraint repair (ops task, only relevant if you ran an old build before 2026-09-27)

```bash
python db/migrate.py
```
If your database ran `db/migrate.py` before the `create_all()` exclusion fix, this run's output includes lines like `+ Part AD2: added missing CHECK ecosystem_installs_scope_check on ecosystem_installs`. **Expected**: exit code `0`, "Migration complete." If it instead reports `! Part AD2: ... duplicate group(s) ...`, the migration correctly refused to force a UNIQUE constraint through over real conflicting data — resolve the listed duplicates manually, then re-run.

---

## 9. Flags reference

| Flag | Default | Effect |
|---|---|---|
| `ENABLE_ECOSYSTEM_MARKETPLACE` | `false` | Mounts `routers/ecosystem_router.py` at all. Nothing in this guide works without it. |
| `COMPLIANCE_SERVICE_ENABLED` | `false` | Whether `static_safety_stage` can catch anything at all (§3.2/§3.3). Pre-existing, unrelated to this initiative — not flipped by it. |
| `ECOSYSTEM_TYPE_SKILL` | `true` | Skills are the only live item type this phase. |
| `ECOSYSTEM_TYPE_PLUGIN`/`_MCP`/`_CONNECTOR` | `false` | Inert placeholders — not testable yet (later phases). |
| `ECOSYSTEM_GATE_SANDBOX_ALLOWED` | unset | Set **only** on the `gate-worker` container/process — never set this anywhere else; it's what makes the Docker-sandbox stage refuse to run outside the dedicated worker. |
| `GITHUB_IMPORT_TOKEN` | unset | Task I — a fine-grained, read-only (public repo contents) GitHub PAT. Without it, `github_repo` imports run anonymously (60 requests/hour). One instance-wide credential, never per-user. |

---

## 10. Known gaps — not testable yet

- No browser UI calls this backend (see §0). `packages/ecosystem-ui` (task F-1) doesn't exist yet.
- `GET /ecosystem/items` / `GET /ecosystem/items/{id}` (catalog list/detail) — still not implemented; only `config`/`capabilities`/`installs`/`jobs` exist as GET endpoints so far.
- Real per-surface (desktop vs. web vs. workspace) UI differences — the backend resolves surfaces correctly (§6b), but no client renders differently per surface yet.
- `admin_disable_org_default` has no HTTP route yet (§5.4) — call the service function directly.
- Admin org policy CRUD (`GET`/`PUT /ecosystem/policy`) — no backing table exists.
- B-19's non-B-10 actions (`share`/`report`/`force_disable`/`unyank`/`deprecate`/`require`/`unrequire`) don't emit `ecosystem.changed` events yet — only install/uninstall/enable/disable/update/rollback do (§6b, `LLD/events.md`).
- Drafts (Create-with-AI) — task B-14, M5, not started.

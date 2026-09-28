# Ecosystem Marketplace — Manual Testing Guide

Living document, updated in the same commit as every milestone that changes tested behavior (matching `docs/ecosystem/design/CHANGELOG.md`'s own convention). Step-by-step manual checks for everything built so far — what to set up, what to call, and the expected result, including negative cases. Written for someone who has never run this feature before.

**Coverage as of this revision**: M0–M3 (create/gate/install/policy/legacy-bridge/builtin-skills, config/capabilities/live-events) plus the pre-M3 hardening items (DB constraint repair, gate deployment separation, secret detection fix, lazy provisioning, fail-closed scanner, gate-worker health), M4 (real web UI — `packages/ecosystem-ui` + `ai-ui`'s `Marketplace.jsx`), M5 (Create-with-AI drafts, chat-runtime skill invocation, the chat "+"/slash-menu client, AgentStudio skill-picker merge, E2E + security suites), and a post-review pass (a real install-lifecycle authentication gap, a `GET /ecosystem/installs` contract gap, install-scope permission enforcement, the "+ Add" menu's full contents, item 6's six chat-based creation flows).

---

## 0. Before you start — what has a UI today, and what doesn't

**Read this first — it changes what "web" and "desktop" testing actually mean right now.**

- **As of M4, `ai-ui/src/components/Marketplace.jsx` is a real, thin wrapper around `packages/ecosystem-ui`'s `<Marketplace>`, calling the real backend through `RealEcosystemClient`** — the old `localStorage`-backed placeholder (`ai-ui/src/marketplaceStore.js`) is deleted. The `/marketplace/*` route is always mounted in `ai-ui`; there is no separate frontend build flag gating it — with the backend's `ENABLE_ECOSYSTEM_MARKETPLACE` off, every API call the screen makes fails/404s (per §1's own flag-check) rather than the route being hidden. §6c below walks through it screen by screen.
- **As of M5 task F-11, `ai-ui`'s chat surface (`Chat.jsx`) also has a real UI client** — a "+" menu and a "Skills" section in the existing "/" slash-command menu, both behind `ECOSYSTEM_CHAT_SKILLS`/`VITE_ECOSYSTEM_CHAT_SKILLS`. §6d below covers it.
- Everything **not** covered by §6c/§6d (creation, the gate, install lifecycle, admin actions, sharing/reporting, external import, legacy bridge) still has **no browser UI** — every check for those sections uses `curl` (or any REST client) directly against the API. This is the honest, current state, not a testing shortcut.
- **Desktop vs. web vs. workspace**: task B-11's resolver (M3) makes this genuinely surface-specific server-side — `surfaces: [...]` on create/install calls, and `GET /ecosystem/config`'s `x-ainxt-product` header, both actually change what's returned. No desktop-native client exists to test against yet; simulate it with `curl ... -H "x-ainxt-product: workspace"` or by passing `client_source` context server-side (chat's own desktop-surface derivation, `LLD/chat-runtime.md`).
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
#    Also start gate-sweeper (separate service, 2026-09-28) — without it, a
#    stuck/orphaned gate run has nothing to detect and re-enqueue it. Never
#    combine the two flags in one process: --gate forks an RQ work-horse per
#    job, and a background thread sharing that process risks a fork+lock
#    deadlock — see docs/ecosystem/design/CHANGELOG.md's 2026-09-28 entry.
docker compose up -d gate-worker gate-sweeper
#    or, running from source:
python workers/start_workers.py --gate --n 1
python workers/start_workers.py --gate-sweeper   # separate terminal/process
```

**Verify the flag actually took effect**: `curl http://localhost:8000/ainxt/v1/api/ecosystem/jobs/does-not-exist` should return `404 {"code":"NOT_FOUND", ...}`, not a 404 from FastAPI's own router-not-found page (which looks different — no JSON `code` field). If you get a bare "Not Found" with no JSON body, `ENABLE_ECOSYSTEM_MARKETPLACE` isn't set, or the gateway needs a restart to pick it up.

**Optional: verify the containerized `ai-ui` build (task B-5)** — the steps above run `ai-ui` from source; if you want to test the actual production Docker image instead (e.g. to reproduce a container-only bug):
```bash
# From the repository root (the Dockerfile's own header comment explains why
# the build context must be the repo root, not ai-ui/):
docker build -f ai-ui/Dockerfile -t ainxt-ai-ui:local .
docker run -d --name ainxt-ai-ui-local -p 18173:5173 ainxt-ai-ui:local
curl -o /dev/null -w "%{http_code}\n" http://localhost:18173/portal/   # expect 200
docker rm -f ainxt-ai-ui-local
```

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

### 3.1 Disallowed license (GPL), non-private scope — blocked before anything else runs

This exact call is now Tier 3 (private, task C's tiered license policy — §3.1a below) since it omits `provision_scope`. To reproduce the **still-unconditional** Tier 1/2 block, add `"provision_scope": "org_default_on"` (needs `marketplace:provision`):
```bash
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "create_via": "write", "item_type": "skill",
    "namespace": "yourname/gpl-skill-org", "display_name": "GPL Skill Org-Wide",
    "description": "d", "category": "general", "license": "GPL-3.0-only",
    "content": {"manifest": {"name": "GPL Skill", "description": "d", "instructions": "..."}, "files": {}},
    "surfaces": ["chat"], "provision_scope": "org_default_on"
  }'
```
**Expected**: `422 {"code": "LICENSE_NOT_ALLOWED_BY_ORG_POLICY", ...}` — rejected at the create step, before an item row is even created (unless your org's admin has already added `GPL-3.0-only` to `allowed_licenses_shared` via §5's admin policy screen, in which case this now succeeds). Confirm nothing was created:
```bash
curl -s "http://localhost:8000/ainxt/v1/api/ecosystem/installs?installed_for=<your_user_id>" -H "Authorization: Bearer $TOKEN"
```
No new row should appear.

### 3.1a Tiered license policy (task C) — private scope is no longer a dead end

**Positive path — private + acknowledged**: the same GPL license, no `provision_scope` (defaults to private):
```bash
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "create_via": "write", "item_type": "skill",
    "namespace": "yourname/gpl-skill-private", "display_name": "GPL Skill Private",
    "description": "d", "category": "general", "license": "GPL-3.0-only",
    "content": {"manifest": {"name": "GPL Skill", "description": "d", "instructions": "..."}, "files": {}},
    "surfaces": ["chat"]
  }'
```
**Expected**: `400 {"code": "LICENSE_ACKNOWLEDGEMENT_REQUIRED", "details": {"reason": "acknowledgement_required"}}` on the first try. Add `"license_acknowledged": true` to the body and repeat — **expected**: `202`, item created, `GET /ecosystem/items/{id}/gate-runs` shows a `license` finding with `code: "LICENSE_WARNING_PRIVATE_SCOPE"` and `severity: "warn"`, and the version's own `gate_verdict` is `"warn"` (or better), never `"fail"` purely for this.

**Missing license, self-authored**: same call with `"license": ""` and no `license_acknowledged` — **expected**: `400`, `details.reason = "missing_license"`. Add `"self_authored": true` instead — **expected**: `202`, and the created item's `license` field reads `"MIT"`.

**Web UI**: `create/CreateForm.tsx`'s License field — click "This item uses a different license" (only shown for the "Just me" scope) to switch from the dropdown to free text; typing a disallowed value shows the acknowledgement checkbox inline (Save stays disabled until checked); clearing it entirely shows the self-authored checkbox instead. `create/UploadFlow.tsx` shows the same two prompts reactively, after the server's real response (the upload's license comes from the zip's `SKILL.md`, so the client can't know upfront). `detail/EditContent.tsx`'s License field behaves the same way for an existing owned item's Edit tab.

**Tier 2 — sharing an already-shared/provisioned item**: install the private GPL item above for yourself (default scope), then try `POST /ecosystem/items/{id}/install` with `"scope": "provisioned"` (needs `marketplace:provision`). **Expected**: `422 {"code": "LICENSE_NOT_ALLOWED_BY_ORG_POLICY", ...}` under the default org policy. `PUT /ecosystem/policy` with `{"allowed_licenses_shared": ["MIT", "Apache-2.0", "GPL-3.0-only"]}` (§5, admin), then retry — **expected**: `201`, success. The admin policy screen's own "Licenses allowed once shared/provisioned/required" field (`AdminPolicies.tsx`) does the same `PUT` on blur.

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

**Every call below now requires `Authorization: Bearer $TOKEN`, belonging to the install's own owner (or an org admin) — this was a real, fixed vulnerability** (`docs/ecosystem/design/LLD/security.md`). Quick negative check before the golden path: call any of the four endpoints below with no `Authorization` header at all — expect `401`, not a mutation. Then repeat as a *different, second* authenticated user in a *different* org — expect `403`/`404`, never a successful mutation of the first user's install.

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

### 4.2 Install scope — "org"/"provisioned"/"required" require marketplace:provision, even bypassing the UI

**As a normal (non-admin) user, in the real web UI**: open any item's Detail page and click Add. **Expected**: the scope options are just "Just me" and (if you have `marketplace:share`) "Share with teammates" — no "Everyone in org," no "Required." `GET /ecosystem/config`'s `caller_permissions` field (`{"can_share": ..., "can_provision": ...}`) is what the UI actually renders from — never a hardcoded assumption from your role.

**Bypassing the UI entirely, as that same normal user**:
```bash
curl -s -X POST http://localhost:8000/ainxt/v1/api/ecosystem/items/<item_id>/install \
  -H "Authorization: Bearer $NORMAL_USER_TOKEN" -H "Content-Type: application/json" \
  -d '{"version_id": "<version_id>", "surfaces": ["chat"], "scope": "provisioned", "origin": "added"}'
```
**Expected**: `403 {"code": "POLICY_FORBIDDEN", ...}` — this was a real, fixed vulnerability (any authenticated user could silently succeed here before this fix; see `docs/ecosystem/design/LLD/install-lifecycle.md`). Repeat with `scope: "required"` and `scope: "org"` — same `403`. Repeat with `scope: "shared"` — succeeds normally (only "org"/"provisioned"/"required" are gated).

**As an admin** (`marketplace:provision`): the same Add dialog shows "Everyone in org" and "Required," and the same `scope: "provisioned"`/`"required"` API calls succeed (`201`).

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

With the gate-worker running (§1 step 5). **Liveness source changed 2026-09-28** — it now reads RQ's own worker registry (`core/job_queue.py`'s `get_queue_worker_liveness()`), not a hand-rolled heartbeat key; see `docs/ecosystem/design/CHANGELOG.md`'s dated entry for why (a fork+lock deadlock, root-caused via direct process inspection).
```bash
curl -s http://localhost:8000/ainxt/v1/api/ecosystem/admin/gate-health -H "Authorization: Bearer $ADMIN_TOKEN"
```
**Expected**: `{"gate_worker_healthy": true, "gate_worker_count": 1, "gate_workers": [{"name": "...", "state": "idle"}], "stuck_verifying_count": 0, "message": null}`.

**Negative case** — stop the gate-worker (`docker compose stop gate-worker`), wait a few seconds for RQ's own worker-registry TTL to expire, then repeat the same call:
**Expected**: `"gate_worker_healthy": false`, `"gate_worker_count": 0`, `"message"` starting with "No gate-worker has reported in...". Create a new item while the worker is stopped, wait 10+ minutes, then check that item's own job status (`GET /ecosystem/jobs/{gate_run_id}`): **expected** a non-null `stuck_message` pointing back at the admin health check, without needing admin access just to see that something is wrong.

### 5.6 Stuck-run sweeper (task B-6, moved to its own process 2026-09-28) — recovers a gate job that was never picked up

The response from §5.5 now also includes a `last_sweep` field: `{"checked": N, "reenqueued": N, "still_in_flight": N, "permanently_failed": N, "reenqueued_gate_run_ids": [...], "permanently_failed_gate_run_ids": [...], "swept_at": "..."}`. The **`gate-sweeper` process** (§1 step 5 — a separate compose service, never combined with `gate-worker` itself) re-runs this sweep every 30 seconds on its own — nothing manual is needed for it to happen, but you can force a reproduction of the actual bug it fixes:

```bash
# 1. With the gate-worker running, create an item, but simulate the RQ enqueue itself
#    failing right after the DB commit succeeds (this is the exact race, LLD/gate.md's
#    own B-6 section) -- easiest to reproduce by temporarily pointing the gateway at an
#    unreachable Redis (or by filling the queue past its 200-item depth limit) for just
#    the one create call, then restoring normal connectivity.
# 2. Check that item's job status immediately: GET /ecosystem/jobs/{gate_run_id} returns
#    status "verifying" with no error -- the create call itself did NOT fail, unlike
#    before this fix.
# 3. Wait for STUCK_VERIFYING_THRESHOLD_SECONDS (600s) plus one sweep tick (<=30s), then
#    repeat step 2: expected the run has now resolved (status "active"/"warn"/"blocked"),
#    and GET /ecosystem/admin/gate-health's last_sweep.reenqueued_gate_run_ids includes
#    this run's gate_run_id.
```

### 5.7 Fork+lock deadlock regression test (real incident, 2026-09-28)

A gate-worker work-horse (RQ's forked per-job child) could deadlock forever if a background thread in the parent process held the DB pool's own lock at the exact instant of fork — root-caused via direct `/proc/<pid>/wchan`/`fd` inspection of a live hung container, not theorized. Fixed by removing the two threads that used to live in the `--gate` process (heartbeat, sweeper — see §5.5/5.6 above) and, as defense in depth, registering `os.register_at_fork(after_in_child=...)` hooks in `db/database.py` and `core/kv/queue.py` that reset any inherited pool/connection state in every forked child, for any future fork in the process.

```bash
# Runs on Linux only (os.fork() is POSIX-only; skipped automatically on Windows).
pytest tests/services/ecosystem/test_gate_health_service.py::test_child_process_can_use_the_db_after_fork_while_the_pools_own_lock_is_held -v
```
**Expected**: passes. This test deterministically holds the connection pool's own internal mutex in a thread that never releases it, forks, and proves the child can still get a working connection quickly — not a timing-dependent race. Verified both ways during this fix: temporarily disabling the `os.register_at_fork` hooks makes this exact test fail cleanly with a bounded `TIMEOUT` result (not hang the suite — the test's own non-blocking `os.waitpid(..., os.WNOHANG)` polling loop force-kills the child after 2s if it never exits on its own).

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

**Subdirectory-scoped GitHub skills (starter-catalog discovery)**: `create_service.create_via_import()`'s `ref` now accepts `"owner/repo[@branch_or_sha]#path/to/skill"` — the `#` dispatches to `import_from_github_path()` instead of the root-only `import_from_github()` (wired in, 2026-09-28). Still **not** exposed through `POST /ecosystem/items` or any other public router endpoint — the only supported caller is `scripts/ecosystem/admin_import.py` (§6a.1 below), an admin-only, container-internal command. `discover_skills_in_repo(repo, ref, path)` itself (finding candidate subdirectories in a repo, used during catalog curation, not at import time) has no HTTP exposure at all. Verify at the adapter layer: `tests/services/ecosystem/import_adapters/test_github_repo_discovery.py` (9 tests, no live network) covers multi-subdirectory discovery, folder-`LICENSE`-overrides-repo-license precedence, repo-license fallback, exclusion on either license signal failing, path-traversal rejection, a truncated-tree hard failure, and `import_from_github_path` bundling only its own folder's files.

### 6a.1 Admin catalog import command (`scripts/ecosystem/admin_import.py`, 2026-09-28)

The only supported way to bulk-load external catalog items (the starter set today; later the External-sources phase) — wraps `create_service.create_via_import()` for a fixed batch, as Discover catalog items (community tier, not org-wide auto-provisioned). **Must run inside a container** sharing the gate-worker's object-storage mount; `store/ecosystem_object_storage.py`'s `assert_local_storage_root_is_mounted()` refuses to proceed otherwise — see §5.7's real incident for why this guard exists (a host-side script wrote 8 real items' object bytes to a location the gate-worker container could never see).

```bash
docker exec ainxt-gateway python -m scripts.ecosystem.admin_import starter \
  --org-id <org_id> --created-by <user_id>
```
**Expected**: one `OK <namespace>: item_id=... version_id=... gate_run_id=... compatibility=...` line per skill in `admin_import.STARTER_CATALOG` (currently 8 — `nidhinjs/prompt-master` was reviewed and excluded, extensive AI-vendor naming throughout its content, a real neutrality violation), a summary count, and exit code 0 only if every import succeeded.

**Negative case — run on the bare host, outside any container**:
```bash
python -m scripts.ecosystem.admin_import starter --org-id x --created-by y
```
**Expected**: immediate `RuntimeError` before any network/DB call, either "...is not an absolute path..." (if `ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR` isn't set at all, host default) or "Refusing to run outside a container..." (if it happens to be set to an absolute path anyway) — never a silent write to a host directory. Covered directly by `tests/store/test_ecosystem_object_storage.py`'s `assert_local_storage_root_is_mounted` tests (relative path refused even with `/.dockerenv` faked present; absolute path outside a container refused; absolute path inside a container passes; s3 backend never checked at all).

A custom batch can be supplied via `--specs-json '[{"namespace": "...", "category": "...", "ref": "owner/repo@sha#path"}, ...]'` instead of the built-in `starter` list.

### 6a.2 External sources catalog crawler (`services/ecosystem/catalog_crawler/`, 2026-09-28) — pre stop-point-1

Builds the pointer-file catalog for the `ecosystem-index` orphan branch (`docs/ecosystem/EXTERNAL_SOURCES_PLAN.md`). As of this entry the crawler itself is real and tested; it has **not been run against a real `sources.yaml` yet** — that requires stop-point-1 sign-off first, and the `ecosystem-index` branch doesn't exist yet either. What follows is how to exercise it once a reviewed `sources.yaml` exists.

```bash
python -c "
from services.ecosystem.catalog_crawler.crawl import run_crawl
report = run_crawl('docs/ecosystem/catalog/sources.yaml', 'docs/ecosystem/catalog/yanked.yaml', '/tmp/ecosystem_index_out')
print(report.to_markdown())
"
```
**Expected**: `/tmp/ecosystem_index_out/catalog/<item_type>/<publisher>/<name>.yaml` per included entry, `/tmp/ecosystem_index_out/index/<item_type>.json` per shard, and a printed crawl report (included/excluded counts, excluded-by-reason breakdown) — this printed report is stop point 2's artifact. This call makes real outbound requests (GitHub API, well-known sites, the MCP Registry) — run it from a network-permitted environment, never in CI (CI's own coverage below uses recorded fixtures instead).

Signing (`services/ecosystem/catalog_crawler/signing.py`) only works for real inside a GitHub Actions job with `permissions: id-token: write` — `sign_index_bytes()` deliberately raises `RuntimeError` everywhere else (verified directly by `test_signing.py`, not mocked). There is nothing to manually test locally beyond that negative case; the real signing path is exercised the first time the crawl workflow actually runs.

**Verification is offline by default** — `verify_index_bytes()` loads the pinned `vendor/sigstore_trusted_root.json` and makes no network call at all, required for air-gapped/firewalled installs and offline snapshot imports. To manually confirm no network call happens:
```bash
python -c "
from services.ecosystem.catalog_crawler.signing import _VENDORED_TRUST_ROOT_PATH
from sigstore.models import TrustedRoot
print(TrustedRoot.from_file(str(_VENDORED_TRUST_ROOT_PATH)))
" # run with network disabled (e.g. a container with no egress) -- still succeeds
```
Refreshing the vendored trust root (an occasional maintainer task, only needed if Sigstore ever rotates its production Fulcio/Rekor keys): run `Verifier.production(offline=False)` once with real network access, then copy whatever lands under `~/.cache/sigstore-python/tuf/https%3A%2F%2Ftuf-repo-cdn.sigstore.dev/trusted_root.json` over `services/ecosystem/catalog_crawler/vendor/sigstore_trusted_root.json`.

**Automated coverage (no live network, recorded fixtures)**:
```bash
docker exec -e POSTGRES_DB=ainxt_test -e PGVECTOR_DB=ainxt_test ainxt-gateway python -m pytest \
  tests/services/ecosystem/catalog_crawler \
  tests/services/ecosystem/import_adapters/test_mcp_registry.py \
  tests/services/ecosystem/import_adapters/test_well_known_discovery.py \
  tests/services/ecosystem/import_adapters/test_github_repo_topic_search.py -q
```
**Expected**: 41 passed (38 from the initial crawler round + 3 new offline-verification tests in `test_signing.py`). (Run inside a container that already has the app's dependency set installed, `sigstore==4.5.0` included — `pip install sigstore` if testing against an image built before this entry landed. `POSTGRES_DB`/`PGVECTOR_DB` must point at a `_test`-suffixed database — `tests/conftest.py`'s autouse fixture refuses to run against anything else, e.g. a container whose own env still points at the real `ainxt_memory` deployment DB.)

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

## 6c. Web UI walkthrough (M4) — Discover, Yours, Detail, Add, Admin **[web]**

```bash
cd ai-ui && npm run dev   # http://localhost:5173, proxies /ainxt/v1/api to the gateway
```
Log in, then navigate to `/marketplace`.

0. **Toolbar (M5 UI-parity review, `components/Toolbar.tsx`)**: the catalog list page's header is one row — title, the 4 type tabs, a vertical separator, the Yours/Discover segmented switch, a search box, filter and sort icon buttons, then "+ Add" — matching `docs/ecosystem/claude_ui_refs/ainxt_customize_mock.html`'s own `.bar`. **Expected**: resize the window down to ~500px wide (or open dev tools' device toolbar) — the row wraps instead of clipping or overlapping (the search box drops to its own full-width line first). This row only renders on the catalog (list) screen — Detail, "Write a skill," Upload, and Import are drill-in screens with just their own Back/Cancel affordance and no tabs/search/add-menu above them (a real, fixed mismatch — the tabs used to show above Detail too, which the reference mock never does). Switching type tabs clears any active search/filter/sort.
1. **Discover tab (default)**: shows category sections seeded by `docs/ecosystem/CONFIG_AND_PRODUCTS.md`'s taxonomy, each item as a card (name, short description, license badge, "New" badge if created within `new_badge_days`). The other three item-type tabs (Plugin/Connector/MCP server) render `ComingSoonTab.tsx` — a static message, no API call, matching `GET /ecosystem/config`'s `item_types[].state: "coming_soon"`.
2. **Search/filter**: typing in the toolbar's search box re-calls `GET /ecosystem/items` with a `q` param; the filter icon opens a popover with category checkboxes (from `config.taxonomy.categories`) and publisher/trust-tier checkboxes (`config.taxonomy.trust_tiers`) — checking either switches you to Discover automatically (filters don't apply to Yours' category/trust). **Expected**: with any search text or filter active, Discover's category-sectioned browse layout is replaced by a flat "N results" grid with a "Clear filters" link — clearing returns to the unfiltered, sectioned view. Search also filters the Yours tab (by name+description) — with a query active and zero matches among your installs, you get a "None of your skills match" message rather than an empty screen. No client-side-only filtering of a stale list — check the Network tab for a fresh Discover request per keystroke (debounced) or filter/sort change. The sort icon offers Featured/Newest/Recently updated/Name — same 4 options as the reference mock, including its "Ranking never uses raw install counts" note (this schema has no install-count field to rank by in the first place).
3. **Card → Detail**: click any card. **Expected**: URL becomes `/marketplace/skills/<namespace>` (the namespace URL-encoded, e.g. `acme%2Ffoo`) — this is the exact `{item_id:path}` route-matching fix from earlier in M4 (`docs/ecosystem/design/CHANGELOG.md`'s namespace-routing entry); a namespace containing a `/` must resolve to a real detail page, not a 404. Detail shows Overview/Versions/Contents/License/Verification/Risk tabs (`components/detail/*.tsx`). **Contents tab**: a file tree on the left (SKILL.md + any bundled files) and, on the right, a Preview/Code icon toggle for whichever file is selected — Preview renders markdown for `.md` files (real formatting, not literal `**`/`*` characters), Code is a read-only, syntax-highlighted view. No Copy Link button exists on this page (removed, not required).
4. **Install/Add**: on an item you haven't installed, as a **normal user** (no `marketplace:share`/`marketplace:provision`) with a clean (non-`warn`) verdict, clicking "Add" installs **immediately with no dialog at all** (private scope, `chat` surface) — matches the reference screenshots' own one-button pattern. **Expected**: button flips to "Adding…" then the item becomes installed without a manual page refresh (reload and confirm it's still installed). If the item's latest verdict is `warn`, a small warning + Cancel/**Continue** confirm still appears first (no scope/surface fields — nothing to choose). **As an admin** (`marketplace:share`/`marketplace:provision`): Add still opens the full dialog (scope radio + surface toggles) — this is the one case with a real choice to make, so it's deliberately kept. To add a *newly*-installed private skill to a different surface (e.g. Desktop) afterward, use Yours → kebab menu → per-surface toggle rather than re-opening this dialog.
5. **Yours tab**: lists everything currently installed for your org+user (`GET /ecosystem/installs` joined with item details). The kebab menu (`KebabMenu.tsx`) offers Disable/Uninstall/Share/Report — each calls the matching endpoint from §4/§6 above; **Expected**: a required item (§4.1) shows `RequiredLock.tsx` instead of an enabled Disable/Uninstall action.
6. **Add menu (top-right "+")**: `AddMenu.tsx` — in order: "Create with AI" (task F-11's own `CreateWithAiModal`, now reachable from here too, not just chat — the same modal, same backend), "Write a skill" (opens `create/CreateForm.tsx`'s multi-step form), "Upload," "Import from GitHub / URL" — each behind the same license/policy checks as the `curl` calls in §2/§3 — then always-visible-but-disabled "Add MCP server"/"Add connector"/"Add plugin" ("Coming soon," never omitted, per `CONTRACTS.md` §8). **[Admin]** an Admin section below a divider: "Add source" (disabled — no backend yet, a real disclosed gap) and "Provision for org" (navigates to `/marketplace/admin/provisioning`). **As a normal user**: confirm the Admin section is entirely absent (not just disabled) — this was a real, fixed bug (see §4.2).
7. **Admin screens [Admin]**: `/marketplace/admin/*` — `AdminFeatured`/`AdminForceDisable`/`AdminGateFindings`/`AdminPolicies`/`AdminProvisioning` (`components/admin/*.tsx`), each a thin form over the `curl`-equivalent admin endpoint in §5. A non-admin account should get redirected/see a permission error, not a blank or broken screen.
8. **Accessibility spot-check**: tab through the Discover grid and a Detail page using only the keyboard (no mouse) — every card, tab, and button should be reachable and show a visible focus ring; screen-reader labels are on `KebabMenu`/`RequiredLock`/icon-only buttons (`aria-label`, verified via `packages/ecosystem-ui`'s own component tests, not just visually).
9. **Theming**: this page renders in ai-ui's light theme (`LIGHT_TOKENS`) only, matching every other ai-ui screen — no dark-mode toggle exists for `/marketplace` specifically (it follows whatever the rest of ai-ui does). If you do exercise `DARK_TOKENS` (Storybook only, or a future host that wires it up), the whole `.eco-root` subtree now paints its own `background`/`color` from those tokens (`HostContext.tsx`, M5 UI-parity review) — before this fix, dark-theme text rendered on the page's leftover *light* background and was barely readable, since nothing had ever painted an actual background before.
10. **Scrolling (M5 UI-parity review)** — before this fix, `ai-ui`'s route slot (`App.jsx`, `h-full overflow-hidden`) clipped anything taller than the viewport instead of scrolling, since `Marketplace.jsx` was the one route wrapper that didn't provide its own scroll region (every other route does, e.g. `AgentsCatalog.jsx`'s `flex-1 overflow-y-auto`). Verify at **1366×768 and 1920×1080**: open a skill with a long SKILL.md (Contents tab), a Discover/Yours list with enough rows to exceed the viewport, and "Write a skill" (`CreateForm.tsx`) with a few supporting files added — each should scroll normally with the mouse wheel/trackpad, with no content clipped at the bottom. Also open the Add dialog on a narrow/short browser window (or with browser zoom increased) — it's no longer centered-and-clipped; it's top-aligned and the overlay itself scrolls if the dialog is taller than the viewport.

### 6c.1 Workspace example host (M5, task F-12) **[compact layout demo]**

```bash
cd packages/ecosystem-ui && npm run example:workspace   # http://localhost:5174
```
**Expected**: renders the real `Marketplace` component in `layout="compact"`, backed by an in-memory `workspace`-shaped config fixture (zero backend dependency by default) — only the `skill` item type is available, no Admin nav entry, no Share action in any kebab menu (all off per the `workspace` product profile, `CONFIG_AND_PRODUCTS.md` §3). To instead point it at a real gateway: `VITE_WORKSPACE_HOST_API=http://localhost:8000/ainxt/v1/api npm run example:workspace` — requires your org to actually have a `workspace` entitlement row (`ecosystem_org_products`), or every call 403s with `POLICY_FORBIDDEN`. This is a test/demo host for this repo only, **not** the production `ainxt-workspace` product.

## 6d. Chat integration (M5, task F-11) — "+" menu, slash-menu skills, Create with AI **[web, desktop-surface via chat]**

```bash
# Backend flag (required for the resolver + orchestrator wiring to do anything):
export ECOSYSTEM_CHAT_SKILLS=true
# Frontend flag (ai-ui build-time; required for the UI pieces below to render at all):
# ai-ui/.env: VITE_ECOSYSTEM_CHAT_SKILLS=true
cd ai-ui && npm run dev
```
**Flag off (either side) — verify no change first**: with `VITE_ECOSYSTEM_CHAT_SKILLS` unset/false, open Chat. **Expected**: no "+" button appears in the toolbar next to Attach/Image/Enhance; typing "/" shows only the pre-existing "Saved prompts" section, no "Skills" section — byte-identical to before this task.

**Flag on**:
1. Install and enable at least one skill for the `chat` surface (`POST /ecosystem/installs` with `surfaces` including `"chat"`, or use a builtin).
2. Reload Chat. A "+" icon now sits at the start of the toolbar row (left of Attach). Click it: **Expected**: "Create a skill with AI…" (active) plus three greyed-out "Add Plugin"/"Add Connector"/"Add MCP server" rows each labeled "Soon".
3. Type `/` in the message box. **Expected**: the existing "Saved prompts" section still appears first (unchanged), followed by a new "Skills" section listing your installed+enabled chat skills with their `slash_command` shown next to the name. Arrow-key Up/Down moves the highlight continuously across **both** sections as one list; Enter on a skill row inserts its slash command into the input (mirroring "Saved prompts"'s own insert-and-focus behavior) rather than sending the message.
4. Send a message starting with an installed skill's exact slash command (e.g. `/exec-assistant do the thing`). **Expected**: the response reflects the skill's own instructions being applied. This is proven server-side, deterministically, without depending on eyeballing an LLM response: `tests/services/ecosystem/test_ecosystem_skill_tools.py`'s `test_apply_chat_skill_integration_expands_a_slash_command_into_the_skill_body` (direct, fast) and `tests/services/ecosystem/test_orchestrator_ecosystem_chat_skills.py`'s `test_flag_on_slash_command_rewrites_question_to_the_skill_body` (through the real `OrchestratorAgent.run()` production path, LLM call boundary mocked) both assert the skill's real instructions text lands in `state.question` before generation — i.e. the exact mechanism "the skill is being used" depends on. A disabled skill's slash command is proven to be correctly ignored the same way (`test_apply_chat_skill_integration_ignores_a_disabled_skills_slash_command`).
4a. **Two real, live bugs found and fixed 2026-09-27, both worth re-checking after any future change near this code**: (a) the `PIPELINE_V2` fast-path tail's skill-chip wrapper generator had a self-referencing closure bug that hung step 4's request forever right after the skill resolved (no error, no timeout) — if a `/name ...` request in step 4 streams nothing at all after a brief pause, suspect this class of bug first, not the model call; (b) the "Using skill: `<name>`" chip (`MessageMeta.jsx`'s `SkillUsedChip`) was silently dropped by the final stream-completion update even when everything else worked — if step 4's response arrives correctly but the chip never appears next to it, that's this bug, not a backend resolution failure (check `docker exec <gateway-container> grep ECOSYSTEM_SKILL <path-to-log>/app/log/app/agent.log` — if `ECOSYSTEM_SKILL_INJECTED_AS_USER_MESSAGE` is there but the chip isn't, it's a frontend rendering bug, not a resolution bug). See `LLD/chat-runtime.md`'s "Safety scoping + two live bugs" section for the root cause of both.

5. **Create with AI**: click "+" → "Create a skill with AI…". **Expected**: a modal opens with an intent textarea. Type a description (e.g. "summarize meeting notes into action items") and click Generate. **Expected**: progress lines stream in (SSE), then a preview card with editable Name/Description/Namespace/License fields and an "Instructions preview" `<details>`. Edit the namespace to something valid (`youruser/your-skill-name`) and click "Save Skill". **Expected (task D, fast path)**: for the common case — a plain-text skill with no bundled scripts, saved to your own private space — the response is already resolved: `status: "active"` immediately, **no "Verifying…" step and no `gate-worker` needed at all** (the manifest + a static safety/hidden-text/prompt-injection check both run synchronously in the request). Reopen the "/" menu or the Marketplace "Yours" tab (§6c step 5) right away — the newly created skill should already be there, auto-installed for you privately. Try it again with an obvious secret pasted into the intent/instructions (e.g. `AKIA...`) or a phrase like "ignore all previous instructions" — **Expected**: `status: "blocked"`, with the specific finding shown, not a generic error; nothing gets auto-installed. If instead the draft ends up with bundled files (rare via this UI, but possible via a more complex AI draft), it keeps the full async gate and the old `Verifying…`/`gate-worker`-dependent behavior described above.
6. **Negative case**: leave the intent box empty — Generate stays disabled. Submit with a namespace left blank in the preview — "Save Skill" stays disabled (`draftContent.namespace` required client-side; the server also rejects it — `LLD/create-with-ai.md`'s "no namespace set" error — try clearing it via devtools if you want to see the server-side rejection specifically).
7. **AgentStudio surface (task B-24, separate flag)**: with `ECOSYSTEM_AGENTSTUDIO_SKILLS` on and `AgentStudio/frontend`'s own `VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS` set, open AgentStudio's skill catalog picker — Ecosystem-sourced skills appear alongside native ones with a small "Marketplace" badge. **Disclosed gap**: picking one there does not yet route its actual invocation through `skill_view`/`read_skill_file` — see `LLD/agentstudio-integration.md`.

---

## 6e. Automated end-to-end tests (M5, Playwright) **[all surfaces this file covers]**

```bash
# 1. A real backend with both flags on, pointed at a real Postgres/Redis
#    (§1 above), plus a real gate-worker actually running against the
#    same DB (§1 step 5) -- several specs need a real gate resolution.

# 2. Two fixed, same-org test users the specs log in as:
python scripts/ecosystem/seed_e2e_test_users.py

# 3. Standalone install + run (first time: npx playwright install chromium,
#    or set channel: 'chrome' in playwright.config.ts if that download is
#    blocked in your environment -- both are documented in the config file):
cd ai-ui && npm install
PLAYWRIGHT_BASE_URL=http://localhost:5175 npx playwright test   # or npm run test:e2e

# workspace-product-profile.spec.ts targets a *different* app/port --
# the F-12 example host (§6c above), zero backend dependency:
cd ../packages/ecosystem-ui && npm run example:workspace
```
**Expected**: `gpl-upload-blocked`, `create-in-chat` (a full, real, LLM-backed generation -- can take over a minute), and all 3 `workspace-product-profile` sub-tests pass. `install-org-scope` passes or gracefully skips depending on the real gate's verdict (see below); `disable-in-chat` can be flaky for the same reason. `uninstall-empty-state`/`upload-to-chat` were failing against a real backend for a real, since-fixed reason, not a spec bug — see §10 and `docs/ecosystem/design/LLD/e2e-testing.md`/`LLD/install-lifecycle.md` (a real `GET /ecosystem/installs` contract gap this suite's own testing surfaced, fixed after being independently hit live during manual smoke testing too); re-run both specs to confirm the fix. Full detail, sequence diagrams, and every edge case found while writing these specs (a profile/role cache, a gate-verdict field to poll, a real live install-scope race): `docs/ecosystem/design/LLD/e2e-testing.md`.

---

## 6f. Adding skills from chat (M5, item 6) **[web, normal user unless noted]**

Needs `ECOSYSTEM_CHAT_SKILLS`/`VITE_ECOSYSTEM_CHAT_SKILLS` on (§6d) and a real gate-worker running (§1 step 5).

1. **Browse skills**: chat's "+" menu → "Browse skills." **Expected (post-2026-09-27)**: this now opens the real Marketplace UI (`packages/ecosystem-ui`'s `<Marketplace>`, `layout="compact"`) in a modal — Yours/Discover tabs, search/filter/sort, the real card grid, and the real "+ Add" menu (Write/Upload/Import/Create-with-AI) — rather than the old bespoke search-and-list panel. Add/Update/Upload/Import all now go through Marketplace's own, already-tested flows (`AddDialog`, `CreateForm`/`UploadFlow`/`ImportFlow`, Detail's "Edit" tab) instead of separate chat-only modals.
2. **Update my skill**: for a skill you own, open it from the Browse-skills modal (or the standalone Marketplace page) and use its "Edit" tab to save a new version — the same flow §6h below tests directly. **Disclosed gap**: the old chat panel's file-upload-based "Update" button (`POST /ecosystem/items/{id}/new-version/upload`) has no equivalent in the embedded Marketplace UI, which only supports editing text in place — a real, known simplification from the 2026-09-27 change, not an oversight.
3. ~~Add as skill from a file~~ — superseded by the Browse-skills modal's own "+ Add" → "Upload (.zip / .skill)" entry (identical backend behavior: license check from `SKILL.md` frontmatter, gate, appears in Yours).
4. **Save this as a skill**: hover any of your own sent messages in chat — **expected**: a small sparkle-icon button appears alongside Edit/Copy. Click it. **Expected**: Create-with-AI opens with the intent textarea already filled from that message's text; the rest of the flow (generate → preview → confirm) is unchanged from §6d.
5. **Import from a URL**: same "+" panel's "Import from a URL" button — paste a `github.com/<owner>/<repo>` URL pointing at a repo with a root `SKILL.md` declaring an MIT/Apache-2.0 license, plus a namespace. **Expected**: identical behavior to Marketplace's own `github_repo` import (§6a) — pins the resolved commit, gates, appears in Yours and the "/" menu.
6. **Live update, no reload**: with chat already open and a skill's "/" menu NOT showing some item, install that item for yourself from a *different* tab (Marketplace, or a raw `curl` to `POST /ecosystem/items/{id}/install`). Go back to the original chat tab **without reloading it** and open the "/" menu again. **Expected**: the newly-installed skill now appears — this used to require a page reload (`disable-in-chat.spec.ts`'s own setup still uses one, since a reload always works too) before this task's SSE-driven live-update fix.
7. **Normal users can't create org/Required from chat**: open Create-with-AI or the Browse-skills Add flow as a normal (non-admin) user — **expected**: no scope option of any kind is ever shown (both flows always create a private, "Just me" install; unlike Marketplace's own Add dialog, there is no scope picker here at all). Confirm server-side too: `POST /ecosystem/items/{id}/install` with a forged `"scope": "org"`/`"provisioned"`/`"required"` as this same user → `403 POLICY_FORBIDDEN` (§4.2).

---

## 6g. Edit skill code, and Copy to my skills for read-only items (task A3) **[web]**

1. **Edit tab appears only for items you own/administer**: open Marketplace → Skills → a skill you created (or, as an admin, any active skill). **Expected**: an "Edit" tab between Contents and Versions. Open a skill you don't own (any built-in item, e.g. Onboarding Buddy) or one that's blocked (failed verdict/yanked). **Expected**: no Edit tab either way; instead a "Copy to my skills" button appears next to Copy link (absent entirely for the blocked one).
2. **File tree + editor**: in the Edit tab, `SKILL.md` is selected by default with syntax highlighting; click "+ Add file", name it e.g. `scripts/run.py` — **expected**: it appears in the tree with Python highlighting once selected. Rename it (pencil icon) to `scripts/run.sh` — **expected**: the tree updates and its highlighting switches to shell. Delete it (trash icon, confirms first) — **expected**: it's gone from the tree.
3. **License field, not SKILL.md text, controls the actual license**: change the License input to `GPL-3.0-only` and click Save. **Expected (task C, superseding an earlier "disables immediately" behavior)**: the first click round-trips to the server; if this item has no non-private install anywhere (Tier 3), an inline acknowledgement checkbox appears ("I'm responsible for complying with this license") and Save stays disabled until it's checked, then a second click succeeds. If the item is already shared/provisioned (Tier 2) instead, an "already shared" reason appears referencing the org's own allowed-licenses policy (§3.1a) — no checkbox, since acknowledgement isn't the right knob there. Set it back to `MIT` (or `Apache-2.0`) and click Save. **Expected**: an inline "Saved as a new version — it's now verifying" banner; `GET /ecosystem/items/{id}/versions` now shows a new row; once the gate resolves pass/warn, this item's own current version updates and (if you had it installed) your install auto-bumps onto it, same as chat's "Update my skill" (§6f.2) — both go through the identical `POST /ecosystem/items/{id}/new-version` endpoint.
4. **Empty SKILL.md is rejected client-side**: clear all of `SKILL.md`'s text. **Expected**: Save disables immediately, no request sent.
5. **Copy to my skills**: on a read-only item, click "Copy to my skills." **Expected**: the normal "Write a skill" form opens pre-filled with that item's display name (suffixed "(copy)"), description, category, license, and instructions/files — but an *empty* namespace field you must fill in yourself. Enter a namespace you own and submit. **Expected**: a brand-new item is created (never modifies the original), gates normally, and you land on its own Detail page — where the Edit tab now appears, since you're its owner.

---

## 6g.1. Delete permanently / Retire (item 1, M5 UI-polish round, 2026-09-28) **[web]**

Real bug found and fixed this round: a private, owned, zero-other-install item's "delete_draft" action was already computed correctly server-side (`items_service.compute_allowed_actions()` — confirmed by the pre-existing `test_get_item_returns_full_detail_by_id_and_by_namespace` test, unchanged), but the frontend's `InstalledMenu` ("Installed ▾" popover, shared verbatim by Detail.tsx and Yours.tsx) never rendered it at all — only the Yours kebab menu did. Fixed in `InstalledMenu.tsx`; also relabeled the kebab's own `delete_draft`/`deprecate` entries from "Delete draft"/"Deprecate" to **"Delete permanently"**/**"Retire"**, and added a confirmation dialog (new `ConfirmDialog.tsx`) before either fires — neither used to have one.

1. **Create with AI (or Write/Upload), then check the Detail page immediately**: after a skill you created lands on its own Detail page (active or still verifying — no status restriction), click "Installed ▾". **Expected**: a "Delete permanently" entry (red/danger) now appears there, in addition to the Yours kebab menu — this is the exact case that was missing before this fix. Click it. **Expected**: a confirm dialog appears ("Delete this skill permanently? ... can't be undone"); `services.ecosystem.items_service.delete_draft()` (and `POST /ecosystem/items/{id}/delete-draft`) is NOT called until you click the dialog's own "Delete permanently" button. Confirm. **Expected**: the item, its version(s), gate findings, stored objects, and your own install are all gone (`test_delete_draft_removes_owner_private_zero_install_item` covers the backend side); you're navigated back.
2. **Share it (or have a teammate install it), then try again**: share the same kind of item, or install it as a second user (`installs_service.install(..., scope="shared")`). **Expected**: "Delete permanently" is no longer offered anywhere (kebab, Installed ▾, or Detail) — instead, the "Installed ▾" menu shows a short note ("Shared with or installed by others, so it can't be deleted.") plus a **Retire** entry. Click Retire → confirm dialog → confirm. **Expected**: `deprecateItem` is called, the item's status moves to `deprecated` (existing installs keep working, matching `services/ecosystem/items_service.py`'s own `deprecate` semantics — unchanged by this round).
3. **Built-in / org-provisioned / required items**: open any of these. **Expected**: no "Delete permanently" or "Retire" appears anywhere for them (they never had `delete_draft`/`deprecate` in `allowed_actions` to begin with — server-side enforced, nothing new to check beyond confirming the UI still shows nothing).
4. **Known, disclosed gap (not fixed this round)**: "Unshare" is a real `allowed_actions` value (`install.scope == "shared"`, offered to the *recipient* of a share) but has no working frontend wiring — `POST /ecosystem/shares/{share_id}/unshare` needs the sharer's own `EcosystemShare.id`, which nothing in `ItemSummary`/`Install` currently exposes to the recipient. Needs its own backend fix (e.g. resolving `share_id` server-side from an install/item id) before a real "Unshare" button can be added — flagged, not wired, to avoid shipping a button that would just 404.

## 6g.2. Grid / List toggle for Yours (item 2, M5 UI-polish round, 2026-09-28) **[web]**

1. **Default and toggle location**: open Marketplace → Skills → Yours (with at least one installed skill). **Expected**: cards render in a grid by default (same visual card design as Discover, `repeat(auto-fill, minmax(240px, 1fr))`), and a Grid/List icon-button pair appears in the toolbar next to the filter/sort buttons — **only when viewing Yours**, not Discover. Click the List icon. **Expected**: the same rows re-render as a single-column list (the pre-existing row layout, unchanged); `data-testid="yours-install-row"`'s own `data-layout` attribute flips between `"grid"`/`"list"` (useful for automated checks). Switch back to Grid — same content, no data reload (a pure client-side re-layout).
2. **Every group keeps its own controls in both layouts**: in either layout, each card/row still shows the status chip (Active/Disabled/Verifying/Blocked), the compact surface toggles, the "Installed ▾" menu, and the kebab (including Delete permanently/Retire from 6g.1 above) — nothing is dropped in grid mode. Group section headings (Created by me / Shared with me / Org provisioned / Required / Added from Discover) render identically in both layouts.
3. **Remembered per browser, not per account**: switch to List, then reload the page (or navigate away and back to Yours). **Expected**: it's still List — persisted via `localStorage` (`ecosystem-ui:yours-layout`), confirmed as a UI preference only, never a server call (no new network request when toggling). Clear that one localStorage key (or use a private/incognito window) and reload. **Expected**: back to the grid default.
4. **Compact layout + keyboard**: narrow the window (or open the host's own compact layout, if available). **Expected**: the toolbar row wraps rather than clipping the toggle. Tab to the Grid/List buttons — **expected**: real, focusable `<button>`s with `aria-pressed` reflecting the active one (not a div with an onClick), reachable and activatable with Tab + Enter/Space alone.

## 6g.3. Discover-visibility, deprecate/delete-draft, starter-catalog, toolbar/card alignment (M5 UI-parity follow-up, 2026-09-28) **[web + backend]**

No real browser available in this environment to drive screenshots — this is the manual walkthrough instead, same convention as 6g.1/6g.2 above. Backend-only checks can be run directly (`pytest`); the UI checks need a real browser at the widths noted.

1. **Private skill never appears in Discover, for anyone** (item 7): as User A, create a skill (Create with AI or Write, default private scope). **Expected**: it does NOT show up in Discover for User A themselves, immediately — not even right after creation. Log in as User B in the *same* org and open Discover. **Expected**: still absent. As User A, open Yours → "Created by me". **Expected**: it's there, with the "Agent-created" trust badge if it went through Create with AI (not "Community" — the tier bug fixed this round), or "Community" if it went through the plain Write/Upload flow (unchanged, correct). Backend regression: `pytest tests/services/ecosystem/test_items_list_get_delete_policy.py::test_list_items_excludes_org_private_from_everyones_discover_feed tests/services/ecosystem/test_drafts_service.py::test_submit_draft_tags_the_item_agent_created_not_community`.
2. **Owner can Retire their own shared item — no 403** (item 9): as the owner of an item, share it with a teammate (or have them install it) so "Delete permanently" is no longer offered. Open "Installed ▾" → click **Retire** → confirm. **Expected**: succeeds (200), item status moves to `deprecated` — before this round's fix, a non-admin owner got a real 403 here despite the UI legitimately showing the button. Backend regression: `pytest tests/services/ecosystem/test_ecosystem_router_http.py::test_deprecate_endpoint_allows_the_items_own_owner_not_just_admins`.
3. **Delete permanently updates chat's skill menu immediately, not eventually** (item 9): install a private skill, confirm it appears in chat's "+"/slash-menu skill list, then delete it permanently from Yours or Detail. **Expected**: it disappears from that chat menu right away, not just after a page reload/cache expiry (the fix wires `delete_draft()` into the same cache-invalidation + `ecosystem.changed` publish every other install mutation already used). Backend regression: `pytest tests/services/ecosystem/test_items_list_get_delete_policy.py::test_delete_draft_publishes_an_uninstalled_event_and_invalidates_the_capabilities_cache`.
4. **Starter-catalog skills now visible in Discover** (item 6): inside the `ainxt-gateway` container, re-run `python -m scripts.ecosystem.admin_import starter --org-id <any org> --created-by <user id>` (idempotent to re-run — see §6a.1 for the full command reference). **Expected**: the 8 skills listed in `docs/ecosystem/catalog/starter-approved.md` now show up in Discover for **every** org, not just the one that ran the import — confirm by opening Discover from a *different* org than the one passed as `--org-id`. Backend regression: `pytest tests/services/ecosystem/test_create_service.py::test_create_via_import_catalog_scope_central_index_creates_an_org_independent_item`. Note: any copy imported by an *older* build of this script is still `org_private`-scoped under whichever org ran it — this re-run does not retroactively fix those rows, it only fixes new imports.
5. **Toolbar — one row at ≥1280px, clean two-row split below it**: open Marketplace at 1920px and 1366px wide. **Expected**: exactly one row — type tabs on the left, then (right-aligned, in this order) Yours/Discover switch, search, filter, sort, Grid/List (Yours tab only), "+ Add" — nothing clipped at the right edge, and the Yours/Discover switch is visually grouped with the right-hand controls, not stuck next to the type tabs. Narrow the window below 1280px. **Expected**: a clean two-row wrap — tabs alone on row 1, the *entire* right-hand cluster together on row 2 (never one control, e.g. Sort, splitting off onto a third line by itself).
6. **Card/Yours-grid anatomy**: open Discover and Yours (grid layout) side by side conceptually — same card shape in both. On a card with a long name, **expected**: the name truncates on one line with a "…" and a native tooltip on hover (not wrapping the card taller). **Expected**: trust/verdict/New/compatibility badges sit on their own line directly under the name, never wrapping. Compare a card with a one-line description against one with a long (2-line) description in the same row. **Expected**: both cards' footers ("+ Add"/"Added ✓" on Discover; surfaces + "Installed ▾" + kebab on Yours) sit at exactly the same height — the footer is pinned to the bottom of the card, not floating just under the description.

---

## 6i. Catalog checking: proportionate gating, priority lanes, ownership repair, sync fast path, pre-check, load test (catalog-checking round, 2026-09-28) **[backend + web]**

Real Chrome via Playwright IS available in this environment (`ai-ui/playwright.config.ts`'s `channel: 'chrome'`) — items marked **[web]** below were actually driven this way, not skipped.

1. **Sync never creates a gate run, structurally, not just today** — `pytest tests/services/ecosystem/test_catalog_sync.py::test_sync_catalog_never_enqueues_a_gate_run`. Manual check: run a real `sync_catalog()` (§6a.2 has the live-catalog values), then confirm `SELECT count(*) FROM ecosystem_gate_runs WHERE version_id IN (SELECT id FROM ecosystem_item_versions WHERE created_at > <sync start time>)` returns exactly the count of items you actually clicked "Add" on since, never more.
2. **A signed catalog item's Add skips the redundant safety re-scan** — install any real catalog item; `GET /ecosystem/items/{id}/gate-runs` → the latest run's `stage_timings.static_safety.status` is `"skipped"` with a `"reason"` mentioning "signed catalog hash matched." An instructions-only item's `supply_chain`/`sandbox` are `"skipped"` too, for the "no scripts or dependencies" reason. A skill bundled with a `.py` file runs `supply_chain`/`sandbox` for real (not skipped) — confirm on `wshobson/agents` or similar bundled-file skill.
3. **Ethics review policy is respected** — `PUT /ecosystem/policy` with `{"ethics_review_policy": "never"}`, install any item for that org, confirm the gate run's `ethics` stage is `"skipped"`. Set it back to `"always"`, confirm ethics runs even for a signed, scriptless catalog item.
4. **Orphaned-ownership repair** — `pytest tests/services/ecosystem/test_items_list_get_delete_policy.py`. Manual check on a real deployment that predates `db/migrate.py` Part AD16: before running the migration, find a private item you created whose "Delete permanently" has mysteriously disappeared (you likely clicked plain "Uninstall" on your own item at some point, not realizing it strips ownership) — `SELECT id, namespace, created_by FROM ecosystem_items WHERE namespace = '<yours>'`. Run `python db/migrate.py`. **Expected**: `created_by` is now populated and "Delete permanently" reappears in `allowed_actions` — no manual DB repair needed per item.
5. **Priority lanes** — `pytest tests/services/ecosystem/test_gate_queue_separation.py::test_enqueue_ecosystem_gate_job_priority_selects_the_right_lane`. Manual check: with the `--gate` worker stopped, enqueue one job at each priority — inspect `ecosystem_gate_queue_low`/`ecosystem_gate_queue`/`ecosystem_gate_queue_high` directly in Redis (`LRANGE`) and confirm each landed on its own queue.
6. **Single-flight** — `pytest tests/services/ecosystem/test_catalog_sync.py::test_materialize_from_catalog_single_flight_second_caller_reuses_the_first_version` plus the real-concurrency proof, `test_a_real_users_add_proceeds_promptly_even_while_a_precheck_is_mid_flight`.
7. **`GET /ecosystem/items` ETag/304** — `curl -i .../ecosystem/items` twice, second time with `-H "If-None-Match: <etag from first response>"` → second response is `304` with an empty body.
8. **Instructions-only Add resolves synchronously, "in about a second"** — `pytest tests/services/ecosystem/test_catalog_sync.py::test_run_gate_synchronously_real_timing_for_an_instructions_only_item` (real timing: p50=23.8ms, p95=41.7ms, orders of magnitude under the 3s budget). Manual check: click Add on any instructions-only real catalog item — `GET /ecosystem/items/{id}/gate-runs` immediately after the Add response returns already shows a resolved verdict, no polling needed. `test_run_gate_synchronously_falls_back_to_async_on_timeout_without_double_executing` covers the timeout-then-fallback path and proves the stage pipeline never executes twice.
9. **Pre-check never blocks a real user, proven under real concurrency** — `pytest tests/services/ecosystem/test_catalog_sync.py::test_precheck_backs_off_immediately_when_item_already_in_flight` (zero-wait back-off) and `test_a_real_users_add_proceeds_promptly_even_while_a_precheck_is_mid_flight` (a real user's Add completes in well under 1s while a simulated pre-check genuinely holds the item's lock). Manual: `PUT /ecosystem/policy` with `{"gate_precheck_enabled": true, "gate_precheck_cap_per_hour": 5}`, set `ECOSYSTEM_CATALOG_PRECHECK=true`, restart the scheduler process — featured catalog items with no version start resolving in the background at low priority; a real Add on any OTHER item is never slower because of it.
10. **Load test, run for real** — `pytest tests/services/ecosystem/test_catalog_load.py -s` (5,000-item synthetic sync + 50 real concurrent threads across 20 skills). Real numbers from this round: sync 53.05s (94 items/s); 50/50 concurrent Adds succeeded, p50=375.5ms, p95=846.4ms; every target item ended up with exactly one version and one gate run — zero duplicates under real contention.
11. **[web] Discover-card and Verification-tab screenshots, real** — `docs/ecosystem/ui-parity-screenshots/catalog-checking-*.png` (taken this round against real Chrome + the real running stack, logged in as `e2e-user-a@ainxt.local`). Two real, disclosed frontend gaps these make visible: (a) a not-yet-added catalog item shows "Verifying…" on both Discover and its Detail page (should be "Catalog checks passed" + enabled "Add" per this round's own `gate.md` contract) — the Detail page's Add button is genuinely `disabled`, not just mislabeled; (b) once installed, the Verification tab correctly renders "skipped" stages but not yet their new `"reason"` text, and its static "Full gate: ..." explanatory copy is now stale for a fast-path/proportionate run. Neither is a backend gap — `gate_service.py`'s `stage_timings` already carries the real reason string (item 2 above proves it server-side); the frontend simply hasn't been updated to read it yet.

**Not built this round, disclosed**: the optional pre-check dispatcher's admin UI (backend + scheduling fully wired, `PUT /ecosystem/policy` is the only way to turn it on right now — no Sources-screen toggle). The two frontend gaps in item 11 above (belong to the UI work on `feature/ainxt-marketplace-backend`, not this round).

---

## 6h. Desktop app (task B-10) **[desktop]**

Everything server-side (header injection, middleware resolution, the chat-skill-index surface derivation) is real and covered by real tests (§10's B-10 entry). This section is what's left to check live, through an actual Electron window — do this yourself, on your own machine (this environment has no display to run Electron in).

1. **Build** (one-time, or after pulling new desktop changes):
   ```bash
   cd desktop
   npm install
   npm run pack        # produces dist/win-unpacked/AiNxt.exe (Windows) — unsigned, unpacked, no installer step needed just to test
   ```
   Expected: no error; `dist/win-unpacked/AiNxt.exe` exists. (`npm run build:win`/`build:mac`/`build:linux` produce a real installer instead, if you want that — not needed just to verify this task.)
2. **Run against your local dev servers** — start your gateway (`uvicorn gateway:app --reload`) and `ai-ui` (`cd ai-ui && npm run dev`, default `http://localhost:5173`) first, then in a separate terminal:
   ```bash
   cd desktop
   AINXT_DEV=1 AINXT_DEV_SERVER_URL=http://localhost:5173 npm run dev
   ```
   (check `desktop/src/main.js`'s own `DEV_SERVER_URL`/`isDev` resolution if the env var name above doesn't match what's actually read in your checkout — it's read once near the top of that file.)
3. **Verify the header is really being sent**: with your gateway running with `LOG_LEVEL=debug` (or just watch its stdout), open the Electron window and use the app normally (log in, open a chat). **Expected**: gateway logs show `client_source=desktop` for those requests (the logger context `set_client_source()` call in `middleware/client_source_middleware.py`), and the response has an `x-ainxt-client-detected: desktop` header (inspect via Electron's own DevTools — `Ctrl+Shift+I` in the window, Network tab).
4. **Verify Marketplace works inside the Electron window**: navigate to `/marketplace` inside the app (same route as the web build — it's the same `ai-ui` bundle, no separate desktop UI). **Expected**: identical behavior to a browser tab, since Marketplace itself doesn't currently branch on surface at all — this step is really confirming the Electron `BrowserWindow` renders the SPA correctly, not a marketplace-specific check.
5. **Verify a chat skill resolves via the desktop surface** (needs `ENABLE_ECOSYSTEM_MARKETPLACE=true` and `ECOSYSTEM_CHAT_SKILLS=true`/`VITE_ECOSYSTEM_CHAT_SKILLS=true` on your gateway/`ai-ui` build, §9): `resolver_service.get_effective_capabilities()` really does filter by surface (`if surface not in (install.surfaces or []): continue`) — so a skill only shows up for a desktop-surface chat turn if its install's `surfaces` list actually includes `"desktop"`. **This matters**: `Detail.tsx`'s quick-Add path (and its Add dialog, for a caller who still sees one) default to `surfaces: ["chat"]` regardless of the DB's own `ecosystem_surfaces.enabled_by_default` seed data (all 5 surfaces, including `desktop`, seed as `true` — but that column isn't even exposed on the `SurfaceRef` API type, so the frontend has no way to read it today; a real, disclosed gap, out of this task's scope to fix). Since the Add-button simplification, a normal user's Add never shows a surfaces toggle at all (no dialog, per that change's own CHANGELOG entry) — so: install a skill (§6f) in a **browser tab** first with a plain click, then open it in Yours → kebab menu → toggle "Desktop" on for that install (an admin who still sees the full Add dialog can instead check "Desktop" there directly, before installing). Then in the *Electron* window's chat, type `/` and confirm the skill appears in the slash-menu, and invoke it. **Expected**: it works, and only because the desktop surface toggle was explicitly turned on — a skill installed with only "Chat" checked will correctly **not** appear when the request's client_source resolves to desktop (that's the filter working correctly, not a bug).

---

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
| `ECOSYSTEM_CHAT_SKILLS` | `false` | Backend half of task B-16/F-11: `agents/orchestrator.py`'s slash-command rewriting + skill-index prompt injection. Off ⇒ `gateway.py` never even computes a surface; the orchestrator's guard is always false. |
| `VITE_ECOSYSTEM_CHAT_SKILLS` (`ai-ui/.env`, build-time) | unset/false | Frontend half of F-11: the "+" menu, the "/" menu's Skills section, and `CreateWithAiModal`. Independent of the backend flag above — both must be on for the full chat flow to work end-to-end, but the frontend flag alone controls whether any of this UI renders at all. |
| `ECOSYSTEM_AGENTSTUDIO_SKILLS` (backend) / `VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS` (`AgentStudio/frontend`, build-time) | `false`/unset | Task B-24: merges Ecosystem-sourced skills into AgentStudio's own catalog picker. No backend flag currently gates `GET /ecosystem/capabilities?surface=agent_studio` itself — only the frontend merge is flag-gated (disclosed as a seam in `docs/ecosystem/design/CHANGELOG.md`'s B-24 entry). |
| `ECOSYSTEM_AGENTSTUDIO_MISSING_DEP` | `false` | Task B-23: `NativeEngine._resolve_catalog_tools()`'s missing-dependency out-parameter, now wired end-to-end when on — `_run_agent()`'s picker-attached-tools resolution passes the out-param, the `agent_start`/`agent_progress` SSE events additively carry a `missing_dependencies` field when non-empty, and `AgentStudio/frontend`'s `ChatPanel.jsx` thinking-timeline renders an amber "‹name› unavailable" chip per entry. Off (default) ⇒ byte-identical SSE/UI to before this task existed — see `docs/ecosystem/design/LLD/agentstudio-integration.md`. **Manual verification steps**: with the flag on, attach a skill/tool to an agent node in a workflow, install it via Ecosystem, save the graph, then uninstall (or force-disable) that item and run the workflow again — the node's thinking-timeline row should show an amber "unavailable" chip for that tool name. With the flag off (default), the same steps produce no chip and no `missing_dependencies` key in the SSE stream (inspect via browser devtools' Network tab on the `/workflows/.../run` SSE response). |
| `ECOSYSTEM_OBJECT_STORAGE_BACKEND` | `local` | Where `store/ecosystem_object_storage.py` persists item content (SKILL.md/bundled files/icons). Read by both the gateway (icon/version upload) and the gate-worker (`gate_service.py`'s `run_gate()`). |
| `ECOSYSTEM_CONNECTOR_REGISTRY_BRIDGE` | `false` | Reserved for a not-yet-implemented feature — `core/config.py` defines and defaults it, but no service/router code branches on it yet anywhere in the repo (confirmed by repo-wide grep as of task B-7). |
| `ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG`/`_AGENTSTUDIO` | `true` | Read only by the standalone `scripts/ecosystem/backfill_legacy_items.py` one-off script — **not** by the live gateway request path: `routers/ecosystem_router.py`'s `list_installs()` always returns `legacy_items=[]` today regardless of either flag ("not done this pass" per that function's own comment). Not in `docker-compose.yml`'s allowlist for this reason (§9a). |

### 9a. Deploy notes — `docker-compose.yml` environment allowlist (task B-7)

Every flag above is an **explicit allowlist** in `docker-compose.yml`'s `environment:` block for each service — the same trap as the pre-existing `FERNET_KEY`/`EMBED_SVC_URL`/`CODEWIKI_*` entries already in that file. Setting a flag in `.env` has **zero effect** on a running container unless that container's own `environment:` block also lists it (`${VAR:-default}`). As of task B-7, the committed `docker-compose.yml` allowlists:
- **`gateway`**: `ENABLE_ECOSYSTEM_MARKETPLACE`, `ECOSYSTEM_CHAT_SKILLS`, `ECOSYSTEM_TYPE_PLUGIN`/`_MCP`/`_CONNECTOR`, `ECOSYSTEM_OBJECT_STORAGE_BACKEND`, `ECOSYSTEM_CONNECTOR_REGISTRY_BRIDGE`, `COMPLIANCE_SERVICE_ENABLED`.
- **`gate-worker`**: `COMPLIANCE_SERVICE_ENABLED`, `ECOSYSTEM_OBJECT_STORAGE_BACKEND` (both real consumers run inside this process: `static_safety_stage.py` and `gate_service.py`'s object-storage call respectively).

**Deliberately excluded, both containers**: `ECOSYSTEM_AGENTSTUDIO_SKILLS`/`ECOSYSTEM_AGENTSTUDIO_MISSING_DEP` (AgentStudio's own separately-deployed backend process only) and `ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG`/`_AGENTSTUDIO` (the standalone backfill script only, not the live request path). `ECOSYSTEM_TYPE_PLUGIN`/`_MCP`/`_CONNECTOR` are excluded from `gate-worker` specifically: `services/ecosystem/gate/mcp_connector_stage.py` is an always-pass no-op today, the flag names appear only in a comment about a future phase. A regression test (`tests/config/test_compose_ecosystem_flags.py`) pins all of the above — both the presences and the deliberate absences — against the real `docker compose config --format json` render (plus static-text checks for the ones that would otherwise be masked by a developer's own local `docker-compose.override.yml`).

A developer's own untracked `docker-compose.override.yml` may add any of the excluded flags for local co-located testing (e.g. running AgentStudio's backend sharing this repo's root `.env`) — that's a legitimate per-developer choice, not something the committed file or its tests should assume or require.

---

## 10. Known gaps — not testable yet

- `admin_disable_org_default` has no HTTP route yet (§5.4) — call the service function directly.
- B-19's non-B-10 actions (`share`/`report`/`force_disable`/`unyank`/`deprecate`/`require`/`unrequire`) don't emit `ecosystem.changed` events yet — only install/uninstall/enable/disable/update/rollback do (§6b, `LLD/events.md`).
- **Partially fixed (task B-10)**: `desktop/` builds a real, working app (`cd desktop && npm install && npm run pack` produces a genuine `dist/win-unpacked/AiNxt.exe` — verified for real, not just `py_compile`), and the full server-side header→surface resolution chain is now real and pinned by tests: `desktop/src/main.js`'s `webRequest.onBeforeSendHeaders` injects `x-ainxt-surface: desktop` on every gateway request → `middleware/client_source_middleware.py` resolves it to `request.state.client_source == "desktop"` (`tests/middleware/test_client_source_middleware.py`, 5/5) → `gateway.py`'s chat-streaming path calls the newly-extracted `services/ecosystem/config_service.resolve_chat_ecosystem_surface()` (`tests/services/ecosystem/test_config_service.py`, 3 new tests) → `agents/orchestrator.py` passes `ecosystem_surface="desktop"` into `resolver_service.get_effective_capabilities()`, which already recognizes `"desktop"` as a valid surface. **Still not exercised end-to-end through an actual running Electron window** (this environment has no display) — see §11 below for the exact commands to run that check locally.
- **Fixed**: `GET /ecosystem/installs` never embedded the documented `item: ItemSummary` on each row (only bare `item_id`) — crashed the real `Yours.tsx` screen, found live during manual smoke testing. Also fixed in the same pass: `item_type` was accepted as a query param but silently never filtered the query. Hardened further after a follow-up review: the endpoint now declares a real `response_model` (so a future regression of this shape 500s instead of shipping silently), new real-HTTP tests cover fresh/deprecated/yanked/provisioned installs specifically, and `Yours.tsx` now shows "This item is no longer available" for any one bad row instead of crashing the whole screen (plus a package-wide `EcosystemErrorBoundary` around `Marketplace.tsx`'s root as a second line of defense). See `LLD/install-lifecycle.md`/`LLD/ui-package.md`. Not yet re-verified against the Playwright suite's `uninstall-empty-state`/`upload-to-chat` specs (§6e), which were failing partly because of this — re-run them after this fix to confirm.
- **Fixed**: `POST /ecosystem/installs/{id}/uninstall`, `.../set-enabled`, `.../update`, and `.../rollback` required no authentication at all — the single most severe finding from this milestone's testing work. See `LLD/security.md`'s Tests section and `tests/services/ecosystem/test_ecosystem_security.py` (12/12 passing, including the fix's own regression tests) for the full writeup.
- **Fixed**: a normal user could see, and successfully submit, "Everyone in org"/"Required" install scope — `POST /ecosystem/items/{id}/install` never validated `scope` against the caller's permissions at all. See §4.2 and `LLD/install-lifecycle.md`/`LLD/config-products.md`.
- **Disclosed, not fixed**: `scope="org"` installs (`installed_for=None`) are invisible to everyone today — `list_installs()` never queries for org-wide (`installed_for IS NULL`) rows, only a specific caller's own. Genuine org-wide default-on visibility already works via a different, already-tested mechanism (`provision_scope` at creation time, or `require_item()`). See `LLD/install-lifecycle.md`.
- **Fixed**: the gate's ethics stage didn't strip a markdown code-fence some model responses wrap their JSON verdict in — resolved to `"pending"` forever for any real, substantive content (confirmed live: 5/5 for longer AI-generated drafts), not just occasional E2E flakiness. See `LLD/gate.md`. Re-run the E2E suite (§6e) after this fix — several specs were flaky specifically because of it.
- **Session-level pinning for chat-invoked skills** (`resolve_pinned_version_id()`) is not wired across multiple turns of one conversation — each turn currently re-resolves fresh, which is safe (never serves stale-but-still-"authorized" content past a revoke) but not CONTRACTS.md §12's exact "resolve once per session" guarantee. See `LLD/chat-runtime.md`'s own disclosure.
- **AgentStudio-picked Ecosystem skills are not yet actually invocable** — task B-24 only merges them into the picker UI; running one during a live AgentStudio workflow would still try to read it through AgentStudio's own native catalog tables, not `skill_view`/`read_skill_file`. Task B-23's missing-dependency signal has the same "resolver built, UI half not wired" shape.
- `POST /ecosystem/items` still does not enforce `Idempotency-Key` despite `CONTRACTS.md` §4 requiring it on that endpoint too (only the two newer draft endpoints, task B-14, enforce it) — a pre-existing gap, disclosed but not fixed by any task so far.
- All 7 named Playwright E2E specs and the consolidated security-test suite now exist and have real run output — see §6e above and `docs/ecosystem/design/LLD/e2e-testing.md`/`LLD/security.md` for exactly what passes, what's flaky and why, and what's disclosed-not-fixed.
- **Item 6 (adding skills from chat, §6f) — 3 new backend tests and 3 new E2E specs were written and syntax/parse-checked but not run against a real database**, to avoid colliding with other live-environment work sharing the same Postgres instance mid-session. Run `pytest tests/services/ecosystem/test_ecosystem_router_http.py -k new_version` and `cd ai-ui && npx playwright test chat-create-appears-in-marketplace-yours installed-appears-in-chat-without-reload chat-create-blocks-org-scope-for-normal-user` once the shared DB is free, and update this line.
- **Item 6's "Import from a URL" only supports `github_repo`**, not `well_known` (the other real import kind, task I) — needs one more form field in the same modal, not built in this pass.
- **Item 6's "attach a .zip/.skill + add as skill" is a standalone button, not wired into `Chat.jsx`'s existing message-attachment pipeline** (a different, RAG/doc-QA-purposed upload system) — the real backend behavior (license check, gate) is identical either way; disclosed as a deliberate scope choice, not a missing feature pretending to be complete.

---

## 11. Rebuild/restart discipline and build-info verification (real incident, 2026-09-27)

A full day of manual testing that day ran against a 15-hour-stale `ainxt-enterprise:local` image — the running `ainxt-gateway`/`ainxt-gate-worker` containers had none of that day's fixes baked in, with no way to tell from the running app. Two things now exist specifically to prevent a repeat:

**Rebuild + verify at the end of every fix round**:
```bash
GIT_COMMIT=$(git rev-parse HEAD) BUILD_TIME=$(date -u +%FT%TZ) docker compose up -d --build gateway gate-worker
```
Then confirm what's actually running matches what you expect — as an admin, `GET /ainxt/v1/api/ecosystem/config`'s `build_info.commit` (or the Marketplace admin nav's own small build-info line, `data-testid="admin-build-info"`) should show the commit you just built. `build_info` is `null` for a non-admin caller (`marketplace:provision` gates it, same signal `caller_permissions.can_provision` uses) — not just hidden client-side, never sent. If you skip the `GIT_COMMIT`/`BUILD_TIME` env vars, both fields read `"unknown"` — a working build, just without the verification value.

Sanity-check any container directly, without relying on the app's own reporting:
```bash
docker exec ainxt-gate-worker sh -c "echo \$GIT_COMMIT \$BUILD_TIME"
```

**Preferring dev-mode hot reload during a fix round** (rebuild-per-round is correct for the final verification pass, but slow for rapid iteration): this must ONLY happen via your own local, untracked `docker-compose.override.yml` — never edit the committed `docker-compose.yml`'s `command:`/`volumes:` for this. A typical override:
```yaml
services:
  gateway:
    volumes:
      - .:/app  # bind-mount the live repo over the image's baked-in copy
    command: ["python", "-m", "uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
  gate-worker:
    volumes:
      - .:/app
    # No --reload equivalent for the RQ worker itself (workers/start_workers.py
    # has no file-watcher) -- restart the container after an edit:
    #   docker compose restart gate-worker
```
`ai-ui`'s own dev server (`cd ai-ui && npm run dev`, already hot-reloading) needs no container override at all if you're running it natively rather than through the `ai-ui` service.

## 12. Gate-worker cold start (real incident, 2026-09-27)

A freshly-started gate-worker's *first* job could hang for RQ's blunt job-level timeout — see `docs/ecosystem/design/LLD/gate.md`'s own dated entry for the full root cause and fix (`workers/start_workers.py`'s `_warmup_gate_modules()`, `core/job_queue.py`'s job-level timeout bumped `300 → 450`). To verify locally:
```bash
docker compose restart gate-worker
docker logs -f ainxt-gate-worker   # expect a "Gate-worker module warmup complete in ~Ns" line before "Listening on ecosystem_gate_queue"
```
Then create/install a skill immediately and confirm its gate run resolves within a few seconds, not anywhere near 300s.

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

## 6c. Web UI walkthrough (M4) — Discover, Yours, Detail, Add, Admin **[web]**

```bash
cd ai-ui && npm run dev   # http://localhost:5173, proxies /ainxt/v1/api to the gateway
```
Log in, then navigate to `/marketplace`.

1. **Discover tab (default)**: shows category sections seeded by `docs/ecosystem/CONFIG_AND_PRODUCTS.md`'s taxonomy, each item as a card (name, short description, license badge, "New" badge if created within `new_badge_days`). The other three item-type tabs (Plugin/Connector/MCP server) render `ComingSoonTab.tsx` — a static message, no API call, matching `GET /ecosystem/config`'s `item_types[].state: "coming_soon"`.
2. **Search/filter**: typing in the search box re-calls `GET /ecosystem/items` with a `q` param; clearing it returns to the unfiltered list. **Expected**: no client-side-only filtering of a stale list — check the Network tab for a fresh request per keystroke (debounced).
3. **Card → Detail**: click any card. **Expected**: URL becomes `/marketplace/skills/<namespace>` (the namespace URL-encoded, e.g. `acme%2Ffoo`) — this is the exact `{item_id:path}` route-matching fix from earlier in M4 (`docs/ecosystem/design/CHANGELOG.md`'s namespace-routing entry); a namespace containing a `/` must resolve to a real detail page, not a 404. Detail shows Overview/Versions/Contents/License/Verification/Risk tabs (`components/detail/*.tsx`).
4. **Install/Add**: on an item you haven't installed, an "Add" button calls `POST /ecosystem/installs`; **Expected**: button becomes "Added"/"Open" without a manual page refresh (optimistic update backed by a real response, not just local state — reload the page and confirm it's still installed).
5. **Yours tab**: lists everything currently installed for your org+user (`GET /ecosystem/installs` joined with item details). The kebab menu (`KebabMenu.tsx`) offers Disable/Uninstall/Share/Report — each calls the matching endpoint from §4/§6 above; **Expected**: a required item (§4.1) shows `RequiredLock.tsx` instead of an enabled Disable/Uninstall action.
6. **Add menu (top-right "+")**: `AddMenu.tsx` — in order: "Create with AI" (task F-11's own `CreateWithAiModal`, now reachable from here too, not just chat — the same modal, same backend), "Write a skill" (opens `create/CreateForm.tsx`'s multi-step form), "Upload," "Import from GitHub / URL" — each behind the same license/policy checks as the `curl` calls in §2/§3 — then always-visible-but-disabled "Add MCP server"/"Add connector"/"Add plugin" ("Coming soon," never omitted, per `CONTRACTS.md` §8). **[Admin]** an Admin section below a divider: "Add source" (disabled — no backend yet, a real disclosed gap) and "Provision for org" (navigates to `/marketplace/admin/provisioning`). **As a normal user**: confirm the Admin section is entirely absent (not just disabled) — this was a real, fixed bug (see §4.2).
7. **Admin screens [Admin]**: `/marketplace/admin/*` — `AdminFeatured`/`AdminForceDisable`/`AdminGateFindings`/`AdminPolicies`/`AdminProvisioning` (`components/admin/*.tsx`), each a thin form over the `curl`-equivalent admin endpoint in §5. A non-admin account should get redirected/see a permission error, not a blank or broken screen.
8. **Accessibility spot-check**: tab through the Discover grid and a Detail page using only the keyboard (no mouse) — every card, tab, and button should be reachable and show a visible focus ring; screen-reader labels are on `KebabMenu`/`RequiredLock`/icon-only buttons (`aria-label`, verified via `packages/ecosystem-ui`'s own component tests, not just visually).
9. **Theming**: this page renders in ai-ui's light theme (`LIGHT_TOKENS`) only, matching every other ai-ui screen — no dark-mode toggle exists for `/marketplace` specifically (it follows whatever the rest of ai-ui does).

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
4. Send a message starting with an installed skill's exact slash command (e.g. `/exec-assistant do the thing`). **Expected**: the response reflects the skill's own instructions being applied — confirm server-side via `LLD/chat-runtime.md`'s own test suite if the UI response isn't conclusive on its own (a slow/rate-limited LLM backend may make this hard to eyeball).
5. **Create with AI**: click "+" → "Create a skill with AI…". **Expected**: a modal opens with an intent textarea. Type a description (e.g. "summarize meeting notes into action items") and click Generate. **Expected**: progress lines stream in (SSE), then a preview card with editable Name/Description/Namespace/License fields and an "Instructions preview" `<details>`. Edit the namespace to something valid (`youruser/your-skill-name`) and click "Save Skill". **Expected**: a status card appears (`Verifying…`/`Live`/etc., matching the gate's real async outcome — leave `gate-worker` running per §1 step 5 or this hangs at "Verifying…" forever, which is itself a useful negative check). Reopen the "/" menu or the Marketplace "Yours" tab (§6c step 5) afterward — the newly created skill should now appear there too, auto-installed for you privately.
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

1. **Browse skills**: chat's "+" menu → "Browse skills." **Expected**: a search box, real `GET /ecosystem/items` results as you type, an "Add" button per not-yet-installed result. Click Add. **Expected**: the button reads "Verifying…" while the real install+gate-poll happens, then a status card (Verifying/Live/Blocked) and a "Manage in Marketplace" link replace it. Search for something already installed — **expected**: no Add button, just the toggle + Manage link.
2. **Update my skill**: for a skill you own (created it yourself), the same panel shows an "Update" button next to it. Click it, attach a new `.zip`/`.skill` file. **Expected**: a new, re-gated version is created (`GET /ecosystem/items/{id}/versions` now shows 2+ rows); once the gate resolves pass/warn, your own install automatically points at the new version (`GET /ecosystem/installs` — check `version_id` changed), with no separate "switch to the new version" step needed. Try this on a skill you do **not** own — **expected**: `403 POLICY_FORBIDDEN` if you call `POST /ecosystem/items/{id}/new-version(/upload)` directly for it.
3. **Add as skill from a file**: same panel's "Add as skill (.zip)" button — pick a `.zip`/`.skill` file, enter a namespace when prompted. **Expected**: identical behavior to Marketplace's own Upload flow (license check from `SKILL.md` frontmatter, gate, appears in Yours) — a GPL-licensed file is blocked with the same `LICENSE_NOT_ALLOWED` reason as §3.1.
4. **Save this as a skill**: hover any of your own sent messages in chat — **expected**: a small sparkle-icon button appears alongside Edit/Copy. Click it. **Expected**: Create-with-AI opens with the intent textarea already filled from that message's text; the rest of the flow (generate → preview → confirm) is unchanged from §6d.
5. **Import from a URL**: same "+" panel's "Import from a URL" button — paste a `github.com/<owner>/<repo>` URL pointing at a repo with a root `SKILL.md` declaring an MIT/Apache-2.0 license, plus a namespace. **Expected**: identical behavior to Marketplace's own `github_repo` import (§6a) — pins the resolved commit, gates, appears in Yours and the "/" menu.
6. **Live update, no reload**: with chat already open and a skill's "/" menu NOT showing some item, install that item for yourself from a *different* tab (Marketplace, or a raw `curl` to `POST /ecosystem/items/{id}/install`). Go back to the original chat tab **without reloading it** and open the "/" menu again. **Expected**: the newly-installed skill now appears — this used to require a page reload (`disable-in-chat.spec.ts`'s own setup still uses one, since a reload always works too) before this task's SSE-driven live-update fix.
7. **Normal users can't create org/Required from chat**: open Create-with-AI or the Browse-skills Add flow as a normal (non-admin) user — **expected**: no scope option of any kind is ever shown (both flows always create a private, "Just me" install; unlike Marketplace's own Add dialog, there is no scope picker here at all). Confirm server-side too: `POST /ecosystem/items/{id}/install` with a forged `"scope": "org"`/`"provisioned"`/`"required"` as this same user → `403 POLICY_FORBIDDEN` (§4.2).

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
| `ECOSYSTEM_AGENTSTUDIO_MISSING_DEP` | `false` | Task B-23: `NativeEngine._resolve_catalog_tools()`'s missing-dependency out-parameter. Not yet wired to any UI response — resolver-side mechanism only (disclosed gap). |

---

## 10. Known gaps — not testable yet

- `admin_disable_org_default` has no HTTP route yet (§5.4) — call the service function directly.
- B-19's non-B-10 actions (`share`/`report`/`force_disable`/`unyank`/`deprecate`/`require`/`unrequire`) don't emit `ecosystem.changed` events yet — only install/uninstall/enable/disable/update/rollback do (§6b, `LLD/events.md`).
- **No desktop-native client exists** — every "desktop surface" check is simulated server-side (chat's own `client_source == "desktop"` derivation, `LLD/chat-runtime.md`), not exercised through an actual desktop app build.
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

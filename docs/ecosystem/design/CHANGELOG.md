# Ecosystem Marketplace — Changelog

One dated entry per implementation task, in the order tasks land. Each entry: what changed, why, files touched, and a pointer to the relevant `HLD.md`/`LLD/` section. Newest entries at the top.

---

## 2026-09-25 — M0: prerequisites

**Task P-0 — Revert the CAPTCHA disable.**
Why: unrelated to this initiative, but the check was left disabled on this branch for local testing and needed reverting before further work landed on top.
Files: `ai-ui/src/components/Login.jsx`.
Design docs: none (not part of the marketplace design).

**Task B-0 — Register feature flags.**
Why: every flag this phase introduces needs to exist before any task that reads it is implemented.
Files: `core/config.py` (11 new flags, matching the file's existing `ENABLE_<NAME>` convention), `tests/config/test_ecosystem_flags.py`.
Design docs: `HLD.md` §4 references the flag-gating principle generally; per-flag detail lives with the task that actually uses each flag.

**Task B-18 — RBAC permissions.**
Why: the creation/sharing/admin endpoints landing in later milestones need permission strings to gate on.
Files: `auth/rbac.py` (6 new permissions: `marketplace:add`, `marketplace:share` at the developer tier; `marketplace:provision`, `marketplace:admin_sources`, `marketplace:admin_policy`, `connectors:admin_shared` at the admin tier), `tests/auth/test_rbac_marketplace_permissions.py`.
Design docs: `LLD/admin.md` (server-side enforcement principle).

**Task B-21 — CI license check, allowlist, third-party notice.**
Why: the platform's MIT/Apache-2.0-only rule needs an automated check before any new marketplace code lands, and one pre-existing dual-licensed dependency needed its notice recorded.
Files: `scripts/ci/ecosystem_license_check.py` (new), `.ecosystem-license-allowlist.json` (new — 78 pre-existing files flagged for a banned-license icon import; re-verified by direct search rather than trusting an earlier count, which turned out to be off by one), `.github/workflows/ci.yml` (new Tier-1 step, blocking), `THIRD-PARTY-NOTICES.md` (new §2.3 entry), `tests/ci/test_ecosystem_license_check.py`.
Design docs: `HLD.md` §5 (open-source hygiene note); no dedicated LLD file — this is CI/process infrastructure, not a runtime component.

**Task D-0 — Design docs skeleton.**
Why: every subsequent task in this plan is required to update these documents in the same commit as its code; the skeleton has to exist first.
Files: `docs/ecosystem/design/HLD.md`, `docs/ecosystem/design/LLD/*.md` (12 files), `docs/ecosystem/design/CHANGELOG.md` (this file).
Design docs: this task created them.

---

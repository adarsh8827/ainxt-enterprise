# Stage 5 catalog sources — proposed candidates (Connectors + Plugins phase)

Status: **proposal for review. Nothing added to `sources.yaml`.** Per the standing rule for this phase, no real crawl of these sources will run until this list is explicitly approved. All data below was checked live against the real source (GitHub API + raw file fetches, 2026-09-30) — nothing here is inferred from memory or a piece/repo's name alone.

## Corrections to this task's own starting assumptions (disclosed up front)

1. **The official MCP Registry crawler (`McpRegistrySource`, `services/ecosystem/import_adapters/mcp_registry.py`) is NOT a gap** — it's already real, wired, and produces `item_type="mcp_server"` pointers today. What was actually missing, and is what this round adds, is (a) a way to hand-pick a *specific* GitHub repo as one `mcp_server` pointer without going through the official registry, and (b) Activepieces community pieces as `connector` pointers. `PointerEntry.item_type`'s own validation only allowed `"skill"`/`"mcp_server"` before this round — widened to add `"connector"` (additive; `"plugin"` was NOT added, since plugins come from the Cowork-roles read-through / org-composition path per `PLUGINS_PHASE_PLAN.md`, not the crawler).
2. **Activepieces community pieces have NO per-piece license field.** Every sampled `packages/pieces/community/<piece>/package.json` (checked live: `slack`, and the general shape is consistent across the directory) has only `name`/`version`/`main`/`types`/`dependencies`/`devDependencies`/`scripts` — no `license` key at all. License comes from the repo's own root `LICENSE` file, which pieces always resolve to (no piece lives under `packages/ee/`, confirmed via a live tree listing — `packages/ee/` contains no `pieces/` subdirectory at all, so there is no community/enterprise intermixing to guard against with a per-piece exclusion list — a **structural** guarantee, not a curated list).
3. **GitHub's own API reports Activepieces' license as `"other"`/`NOASSERTION`** — genuinely misleading for this repo. The real root `LICENSE` file's own text (fetched and read in full) is a standard multi-license-with-explicit-carveout file: everything under `packages/ee/` is separately licensed (its own `packages/ee/LICENSE`, a source-available "Enterprise License", NOT MIT/Apache — confirmed by reading that file's text too), and everything else — including all of `packages/pieces/community/`, verified structurally separate — is "MIT Expat" (a real, standard MIT license body, confirmed by reading the full text). The new crawl code (`import_repo_metadata()`/`import_activepieces_piece()` in `github_repo.py`) does NOT trust the API's `spdx_id` blindly; it falls back to a real text-guess against the actual LICENSE file content whenever the API signal isn't already an allowed license — this is now covered by a real test (`test_import_repo_metadata_falls_back_to_text_guess_when_api_spdx_is_wrong`) modeled directly on this exact repo's real behavior.
4. **`modelcontextprotocol/servers`** (the official MCP example-servers monorepo) was considered and is **NOT** proposed as an `mcp_server_repos` candidate: its real `LICENSE` file (read in full) describes a genuine per-contribution license split (new/relicensed code under Apache-2.0, some older contributions still under MIT, docs under CC-BY-4.0) — there is no single wholesale license for "the repo," and it's a multi-server monorepo (shape-mismatched with `McpServerRepoSource`'s one-repo-one-pointer model, closer to the generic `github_repos` multi-subdirectory crawl). Flagging rather than forcing a wrong-shaped inclusion.

## (a) MCP server repo candidates — 2

Both licenses verified directly via the GitHub API's `license.spdx_id` (no text-guess fallback needed for either — clean, unambiguous single-license repos).

| Repo | License | Category | ToS note | Notes |
|---|---|---|---|---|
| `github/github-mcp-server` | MIT | dev-tools | Talks to the real GitHub API under the caller's own token/scopes — no separate ToS beyond GitHub's own API terms, which any GitHub-integrated tool already operates under. | GitHub's own official MCP server; well-known, single-purpose, actively maintained. |
| `cloudflare/mcp-server-cloudflare` | Apache-2.0 | dev-tools | Talks to the Cloudflare API under the caller's own account/token. | Cloudflare's own official MCP server. Repo's own `description` field is empty on GitHub — a real display description would need a short manual write-up (or pulled from the README) before this becomes a live catalog entry, not fabricated here. |

## (b) Activepieces piece candidates — 12 (of 733 real community pieces)

A small, deliberately conservative starter shortlist — not remotely exhaustive. The full `packages/pieces/community/` directory has **733** subdirectories today (counted live); this list intentionally avoids anything AI-vendor-adjacent by name (several dozen real pieces — `ai`, `aianswer`, `azure-openai`, `aws-bedrock`, `amazon-bedrock`, etc. — exist in the real directory and would very likely trip `scan_for_ai_vendor_names()` on their own descriptions once crawled; that's the existing neutrality gate doing its job, not something to route around by hand-picking safe-sounding names only, but also not something worth proposing as "starter" candidates). All 12 below are widely recognizable, generic productivity/dev-tool integrations with no AI-vendor-name risk.

| Piece slug | Category | Notes |
|---|---|---|
| `slack` | productivity | Messaging integration, extremely widely used. |
| `airtable` | productivity | Spreadsheet/database hybrid, no account-gating concern beyond the user's own Airtable account. |
| `asana` | productivity | Task/project management. |
| `algolia` | dev-tools | Search-as-a-service. |
| `amazon-s3` | dev-tools | Object storage — generic AWS service, not an AI product. |
| `azure-blob-storage` | dev-tools | Object storage — generic Azure service, not an AI product. |
| `apitable` | productivity | Spreadsheet/database hybrid (Airtable-alternative). |
| `baserow` | productivity | Open-source database/spreadsheet tool. |
| `bannerbear` | productivity | Automated image/video generation (non-AI, template-based). |
| `ashby` | productivity | Recruiting/ATS platform. |
| `attio` | productivity | CRM. |
| `appfollow` | dev-tools | App-store review/ranking monitoring. |

Each would become an `item_type="connector"` pointer at `namespace: activepieces/<slug>`, `source_kind: activepieces`, license `MIT` (via the repo-root fallback described above), `tos_note` still needed per-piece before a real crawl (each piece talks to its own real third-party service under the end user's own account — the standing rule "remote services = recorded ToS review instead of license" applies to every one of these, and none has one recorded yet; that's a real, separate decision this doc doesn't make on your behalf).

## What I could NOT verify

- **Per-piece descriptions beyond a generic template.** Activepieces pieces have no discoverable "description" field via their `package.json` (confirmed) and this task didn't scrape each piece's README/`src/index.ts` `displayName`/`description` constant for a richer one — `import_activepieces_piece()` currently returns a templated `"Activepieces integration piece for <slug> (<package_name>)."` string. A real crawl would want a better description; that's a follow-up, not blocking this proposal.
- **Whether any of these 12 pieces' own dependencies pull in a differently-licensed package** (e.g. a vendor SDK with its own, non-MIT terms) — this task only checked the piece's OWN license (via the repo LICENSE fallback), not its `dependencies` list's own licenses. The existing gate's supply-chain stage (stage 4) would need to catch this at install time regardless, same as any other item type.
- **`cloudflare/mcp-server-cloudflare`'s real description** — GitHub reports it as `null`; not fabricated here.

# Ecosystem Marketplace — Team Testing (try-it-out guide)

Distinct purpose from `TESTING_GUIDE.md`: that document is the automated-test/manual-API-check reference for whoever is building or reviewing this feature. This one is for a teammate who just wants to click around and see what's new, without reading source code first. Coverage as of this revision: the Connectors + Plugins phase (Stages 1-5, 2026-09-30) — see `TESTING_GUIDE.md` §14 for the deep-dive version of everything below.

## 1. Turn it on locally

Every flag in this phase defaults `false` — the app behaves exactly as it does today if you change nothing. To try the new stuff, create (or extend) your own **local-only, untracked** `docker-compose.override.yml` at the repo root (docker compose auto-merges it; never edit the committed `docker-compose.yml` for this):

```yaml
services:
  gateway:
    environment:
      ENABLE_ECOSYSTEM_MARKETPLACE: "true"
      ECOSYSTEM_CREDENTIAL_BROKER: "true"
      ECOSYSTEM_TOOL_CALLING: "true"
      ECOSYSTEM_TYPE_CONNECTOR: "true"
      ECOSYSTEM_TYPE_MCP: "true"
      ECOSYSTEM_TYPE_PLUGIN: "true"
      ECOSYSTEM_TYPE_MCP_LOCAL_RUNTIME: "true"   # only if you want to try the local MCP server runtime
```

Then:
```bash
python db/migrate.py                 # picks up the new tables (safe to re-run any time)
docker compose up -d gateway
```
If you're syncing an already-running dev container instead of rebuilding, use `python -m scripts.ecosystem.sync_and_restart_ecosystem_services` (see `TESTING_GUIDE.md` §13) rather than one-off `docker cp`s — it puts gateway/gate-worker/gate-sweeper on the exact same commit and tells you if any of them didn't pick it up.

## 2. What to actually try, stage by stage

**Credential broker** — as an admin, `POST /ainxt/v1/api/ecosystem/admin/oauth-apps` with a fake provider/client id/secret; `GET` the same endpoint back and confirm the secret never comes back in the response. For an already-configured native connector (whatever's in `connectors/registry.py` in your environment), `GET /ainxt/v1/api/ecosystem/connections` should show its real, live status — not a stale cached copy.

**Tool-calling** — nothing to click yet; this is a backend-only additive parameter with no chat surface wired to it (see the "not wired" list below). Skip trying this from the UI.

**Connectors** — create a `connector`-typed item via `POST /ainxt/v1/api/ecosystem/items` (`create_via: "write"`, manifest with a `connector_url`/`oauth`/`tools` block) and watch it appear in Discover's grid as a `ConnectorCard` instead of the usual skill card. Try connecting it — if it declares OAuth and you've registered a matching `EcosystemOAuthApp`, you should get back an `authorize_url`; if not, it should just report `connected` immediately (no OAuth needed).

**Advanced MCP servers** — the "Advanced" UI shell (`AdvancedMcpServers.tsx`) exists but its add-form doesn't call the backend yet, so there's nothing to click through end to end here today. If you want to see the backend side work, create an `mcp_server`-typed item the same way as a connector above (same `POST /ecosystem/items` path).

**Plugins** — create a `plugin`-typed item whose manifest's `parts` references a couple of existing skill/connector namespaces (or use `POST /ecosystem/items/{id}/plugin-compose` on an existing plugin item), then install it. You should see one install per bundled part show up in Yours, each locked against direct uninstall with a message pointing at the plugin — uninstall the plugin itself instead, and confirm the parts free up.

**Catalog Stage 5** — nothing to click; this round only added crawler *configuration* for two new source kinds. No new source has actually been crawled yet — see `docs/ecosystem/catalog/stage5-sources-candidates.md` for what's proposed and awaiting sign-off.

## 3. What's NOT wired end to end yet — please don't file these as bugs

These are real, already-tracked gaps (see `TESTING_GUIDE.md` §14.6 for the full list with file references), not things this round claims to have finished:

- Chat doesn't show a "Connect this app" card, a tool-approval card, or a "using X" indicator during a live conversation yet — the components exist and are tested in isolation, but nothing in `Chat.jsx` renders them yet.
- The Advanced MCP servers "add a custom URL" form doesn't actually call the backend yet.
- There's still only one Connectors-related tab layout live in the app today — the planned "one Connectors tab + an Advanced sub-view" restructuring is built but not switched on in real routing.
- No local/stdio MCP server package has actually been run for real — the lifecycle logic is tested against a mocked Docker client only.
- The Activepieces/MCP-repo catalog candidates aren't live in Discover — nothing has been crawled yet.

## 4. Turning it back off

Delete or comment out the block in your `docker-compose.override.yml` and restart — every flag reverts to its default-off, and the app goes back to today's exact behavior. Nothing about this phase requires a DB rollback to disable; the new tables just sit unused.

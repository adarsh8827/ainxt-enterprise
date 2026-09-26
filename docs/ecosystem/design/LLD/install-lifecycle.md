# LLD — Install lifecycle

**Purpose**: install/uninstall/enable/disable/update/rollback/deprecate/delete-draft, plus sharing, reporting, and admin-side force-disable and featured overrides. Filled in by tasks B-10, B-19.

## Files / functions
_TBD — B-10, B-19._

## API and DB changes
_TBD._

## Sequence diagrams
_TBD._

## Edge cases and errors
_TBD — in particular: the distinction between `uninstall` (removes only the caller's own install record) and `deprecate` (owner/admin-only, retires the item itself) and `delete_draft` (owner-only, hard-deletes a still-private zero-install item)._

## Flags
_TBD._

## Tests
_TBD._

## How to extend
**Plugins/Connectors/MCP servers reuse this exact path, unchanged** (Review round following M1, item E): upload → object storage (`store/ecosystem_object_storage.py`) → gate (`services/ecosystem/gate_service.py`'s orchestrator, stages per `ECOSYSTEM_PLAN.md` §6) → auto-install on `pass`/`warn` for `trigger ∈ {ui_add, chat_create}` (`installs_service.install()`, this file's own subject) → `ecosystem.changed` event (task B-13) → resolved into the caller's available surfaces (`resolver_service.get_effective_capabilities`, task B-11). Nothing about this pipeline is skill-specific — the type-specific parts are entirely upstream of it (manifest parsing differs per type in gate stage 1, and `mcp_connector_stage`/sandbox-stage specifics differ per type in stages 5-7) and downstream of it (how each type surfaces in chat/Agent Studio/desktop). When Plugins/MCP/Connectors flip from `coming_soon` to `available` (a config-only change, `CONTRACTS.md` §8), this install-lifecycle path requires no code change to accommodate them — it was built type-agnostic from the start via `ecosystem_items.item_type` and `ecosystem_installs`, not a skill-only table.

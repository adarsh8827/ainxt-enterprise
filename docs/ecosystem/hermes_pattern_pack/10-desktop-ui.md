# Pattern 10 — Desktop UI: screen-by-screen inventory

## Problem

Five different capability types (Skills, Plugins, MCP, Connectors, Toolsets) need to share a UI
shell without forcing every screen into an identical, ill-fitting layout — while still keeping
install/enable/disable behavior predictable across all five.

## How Hermes does it

**Shell**: one `CapabilitiesView` with a tab bar (Skills / Toolsets / Connectors / Plugins). Two of
the five (Skills, Toolsets) fetch their "installed" list at the *shell* level, not per-tab —
specifically so the tab pill itself can show a live count/badge even for a tab the user isn't
currently viewing.

**Per-screen inventory:**

| Screen | Layout | Marketplace browse | Detail view | Install action | Cache invalidation |
|---|---|---|---|---|---|
| **Skills** | Master-detail list, installed items first, then an "Official Catalog" section | **Embedded iframe** of the public docs site's skills-browse page — not a native list | Before install: name/description/category + a lazy-fetched parsed-frontmatter preview. After: full content + provenance badge (bundled/hub/agent) | Runs a CLI-equivalent install subprocess; polled every ~1.2s for completion | Invalidates the installed-list query, the official-catalog query, *and* the slash-command-completion cache in one shot after any install/uninstall |
| **Plugins** | Flat table, one row per package (a package can have a "desktop half" and/or an "agent half," joined by folder name) | Same embedded-iframe pattern, plus an explicit "Install from Git" button for anything outside the catalog | Inline per-row: version, kind badge, a provenance pill (catalog tier, or raw pinned-SHA for non-catalog installs) | Two paths: catalog pick (from the iframe) or direct git URL | Local reactive store (not a query-cache library), reloaded on profile switch or a manual "rescan" action |
| **MCP** | **Not a list at all** — a raw JSON document editor for the server config, plus a live log pane (stdio/agent tabs) | No dedicated MCP marketplace UI — catalog entries are installed through the *Connectors* tab instead | The JSON block itself is the detail view — no separate structured form | Via the Connectors tab's "local" install flow | N/A — editing is direct-file, saved explicitly |
| **Connectors** | Card-based directory, cards merged from three backends: Nous Portal hosted accounts, already-configured local MCP servers, and platform-adapter plugins | The hosted-catalog cards come from a live authenticated API call; local cards come from the MCP catalog | A dialog showing available tools (with per-tool disable toggles) once connected, or a "connect this way" chooser when reachable both hosted and locally | Hosted: opens system browser + polls an operation-status endpoint until settled. Local: installs the underlying MCP catalog entry | Local nanostores, reseeded from a persisted snapshot so the list isn't empty during a reload |
| **Toolsets** | Same master-detail pattern as Skills | **None** — toolsets are a fixed built-in list, not a catalog/marketplace concept at all | Member tools + usage stats | N/A — nothing to install, only enable/disable | Standard query-cache key, invalidates slash completions on toggle, same as Skills |

**Install-blocked UI state (Skills only)**: there is no pre-install warning banner — a scan-blocked
install is discovered only when the install subprocess exits non-zero; the UI parses the failure
message shape, shows a dedicated "blocked" toast, and offers a **"View scan"** action that fetches
and displays the actual findings on demand. No equivalent structured "blocked" state exists for
Plugins in this pass of the UI.

**The Connectors OAuth flow, concretely**: click Connect → backend returns an authorization URL →
Desktop opens it in the **system's default browser** (not an in-app window) → the app polls an
operation-status endpoint until the backend reports the operation settled → UI flips to
"connected." No local callback server on the Desktop side for this flow.

## Key design decisions and trade-offs

- **Treating "browse the full catalog" as a web page to embed, not a dataset to natively render**,
  is a deliberate scope-reduction: Hermes gets a rich, independently-updatable marketplace browsing
  experience for free (it's just a website) at the cost of the native app not fully owning that UX
  (styling constraints, `postMessage` as the only bridge back).
- **MCP has no dedicated browse UI on purpose** — routing MCP installs through the Connectors tab
  avoids building and maintaining a third near-identical catalog-browsing screen for something users
  encounter less often than skills/plugins.
- **Failure-as-toast-plus-drill-down rather than a structured pre-flight response** is a real UX
  gap, not a considered design choice — it's what "the install path is a CLI subprocess" naturally
  produces, and it's explicitly worth doing better in a fresh implementation (see verdict).

## Failure modes and guards

- Parsing a subprocess's tail output with a regex to detect "was this blocked by the scanner" is
  brittle — a message-format change elsewhere in the pipeline silently breaks the UI's ability to
  show the dedicated blocked-state toast.
- The three-source merge on the Connectors tab (hosted / local / plugin-adapter) means the same
  logical connector can appear to have multiple "ways" to connect, adding real UI complexity for a
  benefit (unifying three backends under one card) that's easy to under-deliver on.

## Verdict: ADAPT

The master-detail list pattern, provenance badges, and per-row enable/disable toggles are solid and
adoptable as-is. The **iframe-embedded marketplace** and the **regex-parsed-subprocess-output
failure UI** are both "worked well enough for a single desktop app," not patterns to carry into a
purpose-built multi-user web product — a server-side platform should own its catalog UI natively
and return typed, structured install results instead of shelling out to a CLI and scraping stderr.

## Server-side translation

- Build one **native, paginated, server-backed** catalog browser per item type (or one shared
  component parameterized by type) instead of an iframe — you already have the catalog as real rows
  (pattern 6), so there's no reason to defer to an embedded website.
- Make install/uninstall/enable/disable **typed API calls returning structured results** (including
  a scan verdict payload when relevant), not a subprocess whose stderr gets regex-matched — this
  removes the fragility Hermes accepts as a consequence of "the UI drives a CLI under the hood."
- Keep the provenance-badge idea (source, tier, pinned version) on every installed-item row — it's
  cheap, high-value UI that directly supports the trust-tier model from pattern 5.
- For a hosted-connector OAuth flow, keep the same shape (external browser + poll-until-settled) —
  it's simpler and more robust across browsers/popup-blockers than an embedded webview, and it's
  already proven at Hermes's scale.
- Show the scan verdict **before** the user commits to installing, not only after a blocked failure
  — since you control the install API directly (no subprocess indirection), there's no reason to
  defer this information to a post-hoc "View scan" drill-down.

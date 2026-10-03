// SPDX-License-Identifier: MIT
// In-memory, fixture-backed EcosystemClient for Storybook stories and
// component tests -- never used against a real backend. Validated against
// the same generated OpenAPI spec in CI (task B-17, CONTRACTS.md §16 point
// 2) so this can't silently drift from what the real backend actually
// returns.

import { EcosystemApiError } from "./EcosystemClient";
import { MOCK_ADMIN_SOURCES, MOCK_CONFIG, MOCK_DETAILS, MOCK_ITEMS, MOCK_LIVE_SEARCH_RESULTS } from "./fixtures";
let installCounter = 0;
let jobCounter = 0;
export class MockEcosystemClient {
  installs = [];
  policy = {
    org_id: "mock-org",
    who_can_add: "all_users",
    allowed_sources: ["central_index"],
    auto_update_default: false,
    allowed_licenses_shared: ["MIT", "Apache-2.0"],
    who_can_share: "all_users",
    ethics_review_policy: "scripts_or_noncatalog",
    gate_precheck_enabled: false,
    gate_precheck_cap_per_hour: 20,
    live_sources_enabled: false
  };
  constructor(options = {}) {
    this.adminSources = options.adminSources ?? MOCK_ADMIN_SOURCES;
    this.config = options.config ?? MOCK_CONFIG;
    const seedItems = options.items ?? Object.values(MOCK_DETAILS);
    this.items = new Map(seedItems.map(i => [i.id, i]));
    this.latencyMs = options.latencyMs ?? 0;
    for (const itemId of options.initialInstalls ?? []) {
      const detail = this.items.get(itemId);
      if (!detail) continue;
      this.installs.push({
        install_id: `install-${itemId}`,
        item: detail,
        version_id: `${itemId}-v1`,
        scope: "provisioned",
        origin: "provisioned",
        installed_by: "mock-user",
        installed_for: "mock-user",
        enabled: true,
        surfaces: ["chat"],
        auto_update: false,
        installed_at: new Date().toISOString()
      });
    }
  }
  async delay(value) {
    if (this.latencyMs > 0) await new Promise(r => setTimeout(r, this.latencyMs));
    return value;
  }
  mustGetItem(idOrNamespace) {
    const byId = this.items.get(idOrNamespace);
    if (byId) return byId;
    const byNs = [...this.items.values()].find(i => i.namespace === idOrNamespace);
    if (byNs) return byNs;
    throw new EcosystemApiError("NOT_FOUND", `no such item ${idOrNamespace}`, false);
  }
  getConfig() {
    return this.delay(this.config);
  }
  listItems(params) {
    let items = [...this.items.values()];
    if (params.item_type) items = items.filter(i => i.item_type === params.item_type);
    if (params.category?.length) items = items.filter(i => params.category.includes(i.category));
    if (params.trust?.length) items = items.filter(i => params.trust.includes(i.trust_tier));
    if (params.verdict?.length) items = items.filter(i => params.verdict.includes(i.latest_verdict));
    if (params.q) {
      const needle = params.q.toLowerCase();
      items = items.filter(i => i.display_name.toLowerCase().includes(needle) || i.description.toLowerCase().includes(needle));
    }
    if (!params.status?.length) items = items.filter(i => i.status !== "yanked");
    if (params.sort === "name") items.sort((a, b) => a.display_name.localeCompare(b.display_name));else items.sort((a, b) => Number(b.is_featured) - Number(a.is_featured));
    return this.delay({
      items,
      next_cursor: null,
      total_hint: items.length
    });
  }

  /** Mock-only ETag simulation (item (d), part 2): a stable hash of the
   * exact fields Discover.tsx's own poll already cares about (id/verdict/
   * install_id/enabled) stands in for the real backend's sha256-of-the-
   * full-response ETag -- identical inputs produce an identical string,
   * which is all a caller of this method actually depends on (it never
   * inspects the ETag's own shape, only compares it for equality). */
  listItemsWithEtag(params, ifNoneMatch) {
    return this.listItems(params).then(data => {
      const etag = JSON.stringify(data.items.map(i => [i.id, i.latest_verdict, i.install_id, i.enabled]));
      if (ifNoneMatch && ifNoneMatch === etag) {
        return {
          data: null,
          etag,
          notModified: true
        };
      }
      return {
        data,
        etag,
        notModified: false
      };
    });
  }
  getItem(idOrNamespace) {
    const item = this.mustGetItem(idOrNamespace);
    // install_id/enabled are read-time-computed from this.installs when a
    // matching install exists there (mirrors the real backend's
    // items_service._item_to_summary(), which resolves the caller's own
    // install fresh on every read) -- but a test/story seeding an item's
    // install_id/enabled directly (no matching this.installs entry) keeps
    // exactly what it seeded rather than being silently overwritten to
    // null; this only ever *adds* the live-tracked state install()/
    // uninstall() produce, never erases an explicitly-seeded fixture.
    const install = this.installs.find(i => i.item.id === item.id);
    if (!install) return this.delay(item);
    return this.delay({
      ...item,
      install_id: install.install_id,
      enabled: install.enabled
    });
  }
  getVersions(itemId) {
    const item = this.mustGetItem(itemId);
    // Fidelity fix (docs/ecosystem/design/LLD/gate.md's catalog-checking
    // round): this used to always fabricate a version, even for an item
    // whose own latest_version is null -- masking the real bug (Add
    // permanently disabled for a not-yet-added catalog item, since the
    // real backend's GET .../versions genuinely returns an empty list
    // when no EcosystemItemVersion exists yet). Matching that now: no
    // fabricated version when there's genuinely none to fabricate.
    if (item.latest_version === null) return this.delay([]);
    return this.delay([{
      id: `${item.id}-v1`,
      version: item.latest_version,
      pinned_sha: null,
      content_hash: "sha256:mock",
      license: item.license,
      gate_verdict: item.latest_verdict,
      created_at: new Date().toISOString(),
      is_current: true
    }]);
  }
  getGateRuns(itemId) {
    const item = this.mustGetItem(itemId);
    const findings = item.latest_verdict === "fail" ? [{
      stage: "license",
      severity: "block",
      code: "LICENSE_NOT_ALLOWED",
      message: "GPL-3.0-only is not MIT/Apache-2.0-compatible."
    }] : item.latest_verdict === "warn" ? [{
      stage: "static_safety",
      severity: "warn",
      code: "EXTERNAL_URL_REFERENCE",
      message: "References an external URL."
    }] : [];
    const mkTiming = ms => ({
      status: item.latest_verdict,
      duration_ms: ms,
      started_at: new Date().toISOString()
    });
    const gate_runs = [{
      id: `${item.id}-gate-1`,
      version_id: `${item.id}-v1`,
      trigger: "ui_add",
      verdict: item.latest_verdict,
      scanner_version: "2026.09.1",
      started_at: new Date().toISOString(),
      finished_at: new Date().toISOString(),
      findings,
      is_fast_path: false,
      queue_position: null,
      stage_timings: {
        manifest: mkTiming(120),
        license: mkTiming(80),
        static_safety: mkTiming(340),
        supply_chain: mkTiming(60),
        sandbox: mkTiming(2100),
        ethics: mkTiming(1800),
        mcp_connector: mkTiming(40)
      }
    }];
    return this.delay({
      gate_runs,
      average_stage_durations_ms: {
        manifest: 110,
        license: 75,
        static_safety: 300,
        supply_chain: 55,
        sandbox: 2200,
        ethics: 1900,
        mcp_connector: 45
      }
    });
  }
  getInstalls(itemType) {
    let installs = this.installs;
    if (itemType) installs = installs.filter(i => i.item.item_type === itemType);
    return this.delay({
      installs,
      legacy_items: [],
      has_any: installs.length > 0,
      next_cursor: null
    });
  }
  getCapabilities(surface) {
    const skills = this.installs.filter(i => i.enabled && i.surfaces.includes(surface)).map(i => ({
      namespace: i.item.namespace,
      display_name: i.item.display_name,
      description: i.item.description,
      slash_command: `/${i.item.namespace.split("/")[1] ?? i.item.namespace}`
    }));
    return this.delay({
      surface,
      skills,
      plugins: [],
      connectors: [],
      mcp_tools: []
    });
  }

  /** Mock-only: no gate/policy check here at all -- the real backend's own
   * "off unless both gates are true" logic lives entirely server-side
   * (live_search_service.py); a story/test that wants to exercise the
   * "section doesn't render" case sets config.live_search_enabled: false
   * on the MOCK_CONFIG it passes in, which Discover.tsx's own gate reads,
   * not this method. A blank query still returns [] here, matching the
   * real endpoint's own contract. */
  searchLive(query) {
    const needle = query.trim().toLowerCase();
    if (!needle) return this.delay({
      results: []
    });
    const results = MOCK_LIVE_SEARCH_RESULTS.filter(r => r.display_name.toLowerCase().includes(needle) || r.description.toLowerCase().includes(needle) || r.namespace.toLowerCase().includes(needle));
    return this.delay({
      results
    });
  }
  createItem(payload) {
    const id = `mock-created-${++installCounter}`;
    const detail = {
      id,
      namespace: payload.namespace,
      item_type: payload.item_type,
      // Item 1 (2026-09-28 live-testing round): an import (`create_via:
      // "import"`) payload carries no display_name at all (the real
      // server derives it from the imported content's frontmatter) --
      // this used to default to the FULL raw namespace (e.g.
      // "acme/imported-tool"), showing a raw publisher/name identifier
      // as the title instead of a clean name. Falls back to just the
      // namespace's own last segment now, matching what the real import
      // adapters (github_repo.py's own name/folder fallback) actually do.
      display_name: "display_name" in payload ? payload.display_name : payload.namespace.split("/").pop() ?? payload.namespace,
      description: "description" in payload ? payload.description : "",
      category: payload.category,
      tags: [],
      icon_url: null,
      trust_tier: "community",
      license: payload.license ?? "MIT",
      status: "active",
      item_scope: "optional",
      is_featured: false,
      is_new: true,
      latest_version: "1.0.0",
      latest_verdict: "pending",
      allowed_actions: ["delete_draft", "report"],
      install_id: null,
      enabled: null,
      install_scope: null,
      install_surfaces: null,
      compatibility: "chat",
      has_other_installs: false,
      share_id: null,
      publisher: {
        slug: payload.namespace.split("/")[0] ?? "acme",
        type: "user"
      },
      attribution: "",
      source: {
        kind: "local",
        url: null
      },
      manifest: {},
      deprecated_at: null,
      deprecated_by: null
    };
    this.items.set(id, detail);
    return this.delay({
      item_id: id,
      version_id: `${id}-v1`,
      gate_run_id: `${id}-gate-1`,
      status: "verifying",
      provision_scope: "private"
    });
  }
  uploadItem() {
    return this.createItem({
      create_via: "write",
      item_type: "skill",
      namespace: "mock/uploaded",
      display_name: "Uploaded",
      description: "",
      category: "general",
      content: {
        instructions: "",
        files: []
      }
    });
  }
  uploadIcon() {
    return this.delay({
      icon_url: "url:/mock/icon.png"
    });
  }
  createNewVersion(itemId, content, license, _tierOptions) {
    const item = this.mustGetItem(itemId);
    item.manifest = {
      instructions: content.instructions,
      files: Object.fromEntries(content.files.map(f => [f.name, f.content]))
    };
    if (license) item.license = license;
    item.latest_verdict = "pending";
    return this.delay({
      item_id: itemId,
      version_id: `${itemId}-v${++installCounter}`,
      gate_run_id: `${itemId}-gate-${jobCounter}`,
      status: "verifying"
    });
  }
  install(itemId, body) {
    const item = this.mustGetItem(itemId);
    const installId = `install-${++installCounter}`;
    // A not-yet-added catalog item's own "+ Add" omits version_id entirely
    // (catalogState.ts's isNotYetAddedCatalogItem()) -- the mock simulates
    // the real server's materialize_from_catalog() by fabricating a fresh
    // version id here, same as it always fabricates job/install ids.
    const versionId = body.version_id ?? `${itemId}-materialized-v1`;
    this.installs.push({
      install_id: installId,
      item,
      version_id: versionId,
      scope: body.scope,
      origin: body.origin,
      installed_by: "mock-user",
      installed_for: "mock-user",
      enabled: true,
      surfaces: body.surfaces,
      auto_update: false,
      installed_at: new Date().toISOString()
    });
    // Job-shaped (item 2, 2026-09-29 live-test round: install_item()'s own
    // real response) -- install_id is additive on Job (types.ts) so
    // callers can show "Added" the instant this resolves, with no
    // separate GET round trip just to learn the id install() itself just
    // created.
    return this.delay({
      job_id: `job-${++jobCounter}`,
      status: "active",
      item_id: itemId,
      version_id: versionId,
      gate_run_id: null,
      error: null,
      install_id: installId
    });
  }
  uninstall(installId) {
    this.installs = this.installs.filter(i => i.install_id !== installId);
    return this.delay(undefined);
  }
  setEnabled(installId, enabled) {
    const row = this.installs.find(i => i.install_id === installId);
    if (row) row.enabled = enabled;
    return this.delay(undefined);
  }
  setSurfaces(installId, surfaces) {
    const row = this.installs.find(i => i.install_id === installId);
    if (row) row.surfaces = surfaces;
    return this.delay(undefined);
  }
  updateInstall() {
    return this.delay(undefined);
  }
  rollbackInstall() {
    return this.delay(undefined);
  }
  shareItem() {
    return this.delay(undefined);
  }
  unshare() {
    return this.delay(undefined);
  }
  reportItem() {
    return this.delay(undefined);
  }
  deprecateItem(itemId) {
    const item = this.items.get(itemId);
    if (item) item.status = "deprecated";
    return this.delay(undefined);
  }
  deleteDraft(itemId) {
    this.items.delete(itemId);
    return this.delay(undefined);
  }
  getJob(jobId) {
    return this.delay({
      job_id: jobId,
      status: "active",
      item_id: null,
      version_id: null,
      gate_run_id: null,
      error: null
    });
  }
  getPolicy() {
    return this.delay(this.policy);
  }
  setPolicy(body) {
    this.policy = {
      ...this.policy,
      ...body
    };
    return this.delay(this.policy);
  }
  getAdminSources() {
    return this.delay(this.adminSources);
  }
  syncCatalogNow() {
    const shards = [{
      shard: "skill",
      fetched: true,
      verified: true,
      error: null,
      created: 0,
      updated: this.adminSources.last_sync?.shards[0]?.updated ?? 0,
      yanked: 0
    }, {
      shard: "mcp_server",
      fetched: true,
      verified: true,
      error: null,
      created: 0,
      updated: 0,
      yanked: 0
    }];
    this.adminSources = {
      ...this.adminSources,
      last_sync: {
        ok: true,
        shards,
        synced_at: new Date().toISOString()
      }
    };
    return this.delay({
      ok: true,
      shards
    });
  }
  getGateHealth() {
    return this.delay({
      gate_worker_healthy: true,
      last_heartbeat: new Date().toISOString(),
      heartbeat_stale_after_seconds: 90,
      stuck_verifying_count: 0,
      stuck_verifying_threshold_seconds: 600,
      message: null,
      last_sweep: null
    });
  }
  getGateFindings() {
    return this.delay([...this.items.values()].filter(i => i.latest_verdict === "fail" || i.latest_verdict === "warn").map(i => ({
      gate_run_id: `${i.id}-gate-1`,
      item_id: i.id,
      version_id: `${i.id}-v1`,
      trigger: "ui_add",
      verdict: i.latest_verdict,
      started_at: new Date().toISOString(),
      findings: [{
        stage: "license",
        severity: "warn",
        code: "MOCK_FINDING",
        message: "mock finding"
      }]
    })));
  }
  setFeatured(itemId, featured) {
    const item = this.items.get(itemId);
    if (item) item.is_featured = featured;
    return this.delay(undefined);
  }
  clearFeaturedOverride() {
    // The mock has no separate platform-level-vs-override distinction to
    // revert to -- a no-op is the correct mock behavior here.
    return this.delay(undefined);
  }
  forceDisable(itemId) {
    const item = this.items.get(itemId);
    if (item) item.status = "yanked";
    return this.delay(undefined);
  }
  unyank(itemId) {
    const item = this.items.get(itemId);
    if (item) item.status = "active";
    return this.delay(undefined);
  }
  requireItem() {
    return this.delay(undefined);
  }
  unrequireItem() {
    return this.delay(undefined);
  }
  streamDraft(_itemType, _intent, onTurn) {
    let cancelled = false;
    const steps = ["intent", "clarify", "blueprint", "content", "critique"];
    let i = 0;
    const tick = () => {
      if (cancelled || i >= steps.length) return;
      onTurn({
        stage: steps[i],
        text: `mock ${steps[i]} turn`
      });
      i += 1;
      setTimeout(tick, 10);
    };
    setTimeout(tick, 10);
    return {
      cancel: () => {
        cancelled = true;
      }
    };
  }

  /** Install-state-consistency round (2026-09-29): a real subscriber
   * registry (not a no-op) so a component test can prove "an
   * ecosystem.changed event arrives -> this screen refetches" by calling
   * the test-only emitChangeEvent() below, the same way the real
   * RealEcosystemClient's streamChanges() would fire on a real SSE frame.
   * Never fires on its own -- there is no real backend here to publish
   * anything. */
  changeListeners = new Set();
  streamChanges(onEvent) {
    this.changeListeners.add(onEvent);
    return () => {
      this.changeListeners.delete(onEvent);
    };
  }

  /** Test-only: simulates a real ecosystem.changed SSE frame arriving --
   * e.g. to prove a screen refetches on a change made by a DIFFERENT
   * (mocked) tab/caller, without needing a real Redis/SSE round trip. */
  emitChangeEvent() {
    for (const listener of this.changeListeners) listener();
  }

  // ── Connectors phase (mock state) ───────────────────────────────────
  connections = new Map();
  oauthApps = [];
  pendingToolCalls = [];

  /** Test/story seam: pre-seed a connection status, e.g. to render a card
   * as already-connected or needing reauth without going through a full
   * connect() round trip first. */
  seedConnection(conn) {
    this.connections.set(conn.connector_ref, conn);
  }
  seedPendingToolCall(call) {
    this.pendingToolCalls.push(call);
  }
  listConnections() {
    return this.delay([...this.connections.values()]);
  }
  connect(connectorRef) {
    // Mock never simulates a real OAuth redirect -- resolves straight to
    // "connected", matching a header/API-key connector's own no-redirect
    // path. A story/test wanting to exercise the redirect branch calls
    // seedConnection() with status: "connecting" directly instead.
    const conn = {
      connector_ref: connectorRef,
      item_id: null,
      status: "connected",
      last_connected_at: new Date().toISOString(),
      expires_at: null
    };
    this.connections.set(connectorRef, conn);
    return this.delay({
      status: "connected"
    });
  }
  completeOAuthCallback(connectorRef) {
    return this.connect(connectorRef);
  }
  disconnect(connectorRef) {
    this.connections.set(connectorRef, {
      connector_ref: connectorRef,
      item_id: null,
      status: "not_connected",
      last_connected_at: null,
      expires_at: null
    });
    return this.delay({
      status: "not_connected"
    });
  }
  reconnect(connectorRef) {
    return this.connect(connectorRef);
  }
  listOAuthApps() {
    return this.delay(this.oauthApps);
  }
  createOAuthApp(body) {
    const app = {
      id: `oauth-app-${++installCounter}`,
      provider: body.provider,
      client_id: body.client_id,
      redirect_uri: body.redirect_uri ?? null,
      scopes: body.scopes ?? [],
      created_by: "mock-user",
      created_at: new Date().toISOString()
    };
    this.oauthApps.push(app);
    return this.delay(app);
  }
  deleteOAuthApp(id) {
    this.oauthApps = this.oauthApps.filter(a => a.id !== id);
    return this.delay(undefined);
  }
  listPendingToolCalls() {
    return this.delay([...this.pendingToolCalls]);
  }
  approveToolCall(id) {
    this.pendingToolCalls = this.pendingToolCalls.filter(c => c.id !== id);
    return this.delay({
      status: "approved"
    });
  }
  denyToolCall(id) {
    this.pendingToolCalls = this.pendingToolCalls.filter(c => c.id !== id);
    return this.delay({
      status: "denied"
    });
  }
  composePlugin(itemId, parts) {
    const item = this.mustGetItem(itemId);
    item.manifest = {
      ...item.manifest,
      parts
    };
    return this.delay({
      item_id: item.id,
      version_id: `version-${++installCounter}`,
      gate_run_id: `gate-${installCounter}`,
      status: "verifying"
    });
  }
  mcpRuntimeInstances = [];
  listMcpRuntimeInstances() {
    return this.delay([...this.mcpRuntimeInstances]);
  }
}
export { MOCK_ITEMS };
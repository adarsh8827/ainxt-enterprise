// SPDX-License-Identifier: MIT
// The one interface every screen in this package depends on -- never a
// direct fetch() call from a component. RealEcosystemClient.ts is the
// fetch-based implementation consuming the live backend
// (docs/ecosystem/CONTRACTS.md §17); MockEcosystemClient.ts is a
// fixture-backed implementation for Storybook/component tests, validated
// against the same generated OpenAPI spec in CI (task B-17's contract
// test, CONTRACTS.md §16 point 2).
import type {
  AdminSourcesInfo, Capabilities, ConnectionStatus, ConnectResult, ConnectorConnection, CreateImportPayload, CreateResult,
  CreateWritePayload, EcosystemConfig, EditableContent, GateFindingRow, GateHealth, GateRun, GateRunsResponse,
  InstallsResponse, ItemDetail, ItemListResponse, ItemVersion, Job, ListItemsParams, LiveSearchResult, NewVersionResult,
  OAuthApp, OrgPolicy, PendingToolCall, ShardSyncStatus,
} from "../types";

export interface EcosystemClient {
  getConfig(product?: string): Promise<EcosystemConfig>;
  listItems(params: ListItemsParams): Promise<ItemListResponse>;
  /** Item (d), part 2 (2026-09-29 live-test round): same data as
   * listItems(), but ETag-aware for background refresh -- pass the
   * previously-cached ETag (catalogCache.ts's own DiscoverCacheEntry.etag)
   * as `ifNoneMatch`. GET /ecosystem/items already returns an ETag on
   * every response and honors If-None-Match with a real 304
   * (routers/ecosystem_router.py's list_items()); this resolves with
   * `notModified: true` and `data: null` in that case, so a caller's
   * cached data is only ever replaced when the server actually returns
   * fresh content, never on a 304. `listItems()` itself is untouched --
   * this is additive, only Discover.tsx's own cached-background-refresh
   * path calls it. */
  listItemsWithEtag(
    params: ListItemsParams, ifNoneMatch?: string | null,
  ): Promise<{ data: ItemListResponse | null; etag: string | null; notModified: boolean }>;
  getItem(idOrNamespace: string): Promise<ItemDetail>;
  getVersions(itemId: string): Promise<ItemVersion[]>;
  getGateRuns(itemId: string): Promise<GateRunsResponse>;
  getInstalls(itemType?: string): Promise<InstallsResponse>;
  getCapabilities(surface: string): Promise<Capabilities>;
  /** GET /ecosystem/search/live -- Discover's "From the web" section.
   * Only ever called when config.live_search_enabled is true; the backend
   * itself also returns `{results: []}` for a blank query or either gate
   * off (never raises), so this is safe to call defensively too. */
  searchLive(query: string): Promise<{ results: LiveSearchResult[] }>;

  createItem(payload: CreateWritePayload | CreateImportPayload, idempotencyKey: string): Promise<CreateResult>;
  uploadItem(form: FormData, idempotencyKey: string): Promise<CreateResult>;
  uploadIcon(file: File): Promise<{ icon_url: string }>;

  /** POST /ecosystem/items/{id}/new-version (CONTRACTS.md §10.1) -- an
   * immutable new version of an item the caller owns/administers, e.g.
   * item A3's "Edit skill code" Save action. Never creates a new item.
   * `tierOptions` is the tiered license policy's own knobs (ECOSYSTEM_PLAN.md
   * §11.2, Tier 3) -- only relevant when `license` isn't MIT/Apache-2.0. */
  createNewVersion(
    itemId: string, content: EditableContent, license?: string,
    tierOptions?: { licenseAcknowledged?: boolean; selfAuthored?: boolean },
  ): Promise<NewVersionResult>;

  /** `version_id` is optional (docs/ecosystem/design/LLD/gate.md's
   * catalog-checking round): omitted entirely for a not-yet-added catalog
   * item (catalogState.ts's isNotYetAddedCatalogItem()) -- the server
   * materializes real content and creates the version/gate run itself at
   * install time (`materialize_from_catalog()`) rather than the caller
   * needing to look one up first (there isn't one to look up). Every
   * other caller keeps sending a real version id, unchanged. */
  install(itemId: string, body: { version_id?: string; surfaces: string[]; scope: string; origin: string }, idempotencyKey: string): Promise<Job>;
  uninstall(installId: string): Promise<void>;
  setEnabled(installId: string, enabled: boolean): Promise<void>;
  setSurfaces(installId: string, surfaces: string[]): Promise<void>;
  updateInstall(installId: string, versionId: string): Promise<void>;
  rollbackInstall(installId: string, versionId: string): Promise<void>;

  shareItem(itemId: string, installId: string, sharedWithType: string, sharedWithId: string): Promise<void>;
  unshare(shareId: string): Promise<void>;
  reportItem(itemId: string, reason: string): Promise<void>;
  deprecateItem(itemId: string): Promise<void>;
  deleteDraft(itemId: string): Promise<void>;

  getJob(jobId: string): Promise<Job>;

  getPolicy(): Promise<OrgPolicy>;
  setPolicy(
    body: Partial<Pick<
      OrgPolicy,
      "who_can_add" | "allowed_sources" | "auto_update_default" | "allowed_licenses_shared"
      | "who_can_share" | "ethics_review_policy" | "gate_precheck_enabled" | "gate_precheck_cap_per_hour"
      | "live_sources_enabled"
    >>,
  ): Promise<OrgPolicy>;
  getGateFindings(limit?: number): Promise<GateFindingRow[]>;
  getGateHealth(): Promise<GateHealth>;
  /** Task 3a: the admin Sources screen's one aggregate read -- catalog
   * URL/last-sync status, approved well-known sites, this org's own
   * EcosystemSource rows, and GitHub credential status. */
  getAdminSources(): Promise<AdminSourcesInfo>;
  /** POST /ecosystem/admin/catalog-sync -- runs sync_catalog() synchronously
   * and returns its real report (also persisted server-side as the new
   * "last sync" status getAdminSources() reads back -- this response has
   * no synced_at of its own, unlike AdminSourcesInfo.last_sync). */
  syncCatalogNow(): Promise<{ ok: boolean; shards: ShardSyncStatus[] }>;
  /** PUT /ecosystem/featured/{item_id} -- an explicit org-level override. */
  setFeatured(itemId: string, featured: boolean): Promise<void>;
  /** DELETE /ecosystem/featured/{item_id} -- removes the org's override
   * entirely, reverting to the platform-level is_featured value. Distinct
   * from setFeatured(id, false), which sets an explicit "not featured"
   * override rather than clearing it. */
  clearFeaturedOverride(itemId: string): Promise<void>;
  forceDisable(itemId: string): Promise<void>;
  unyank(itemId: string): Promise<void>;
  requireItem(itemId: string): Promise<void>;
  unrequireItem(itemId: string): Promise<void>;

  streamDraft(itemType: string, intent: string, onTurn: (turn: unknown) => void): { cancel: () => void };

  /** Install-state-consistency round (2026-09-29): subscribes to the
   * real, already-existing per-org `ecosystem.changed` event stream
   * (CONTRACTS.md §13, `GET /ecosystem/events/stream`) -- the same
   * mechanism ai-ui's chat "/" menu (useEcosystemChatSkills.js)
   * already uses to pick up an install/uninstall without a reload.
   * `onEvent` fires once per event (no payload parsing needed by the
   * caller -- every consumer here just wants "something changed,
   * refetch," never a specific field), including for a change made in
   * a DIFFERENT browser tab, which is what makes this the cross-tab
   * half of the fix (this module's own installStore.ts is per-tab,
   * in-memory only). Returns an unsubscribe function.
   *
   * Optional -- callers guard with `client.streamChanges?.(...)`.
   * Same-tab consistency via installStore.ts works fully either way;
   * this is only the additional cross-tab guarantee. Several existing
   * component test files construct a minimal ad-hoc client object typed
   * `as EcosystemClient` rather than the full MockEcosystemClient --
   * making this required would break every one of them for an
   * unrelated capability they don't exercise. */
  streamChanges?(onEvent: () => void): () => void;

  // ── Connectors phase (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1) ──────
  /** GET /ecosystem/connections -- one row per connector/mcp_server ref
   * this caller has ever interacted with (native connectors are
   * read-through from connectors/registry.py's own status; nothing here
   * duplicates that store). */
  listConnections(): Promise<ConnectorConnection[]>;
  /** Starts (or completes, for a no-OAuth connector) a connect flow.
   * "connecting" + authorize_url means the caller must redirect the user
   * there; the OAuth provider then redirects back to a page that calls
   * completeOAuthCallback(). */
  connect(connectorRef: string): Promise<ConnectResult>;
  completeOAuthCallback(connectorRef: string, code: string, state: string): Promise<ConnectResult>;
  disconnect(connectorRef: string): Promise<{ status: ConnectionStatus }>;
  reconnect(connectorRef: string): Promise<ConnectResult>;

  listOAuthApps(): Promise<OAuthApp[]>;
  createOAuthApp(body: { provider: string; client_id: string; client_secret: string; redirect_uri?: string; scopes?: string[] }): Promise<OAuthApp>;
  deleteOAuthApp(id: string): Promise<void>;

  listPendingToolCalls(): Promise<PendingToolCall[]>;
  approveToolCall(id: string): Promise<{ status: "approved" }>;
  denyToolCall(id: string): Promise<{ status: "denied" }>;
}

export class EcosystemApiError extends Error {
  code: string;
  details?: Record<string, unknown>;
  retryable: boolean;

  constructor(code: string, message: string, retryable: boolean, details?: Record<string, unknown>) {
    super(message);
    this.code = code;
    this.retryable = retryable;
    this.details = details;
  }
}

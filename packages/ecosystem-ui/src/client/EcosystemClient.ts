// SPDX-License-Identifier: MIT
// The one interface every screen in this package depends on -- never a
// direct fetch() call from a component. RealEcosystemClient.ts is the
// fetch-based implementation consuming the live backend
// (docs/ecosystem/CONTRACTS.md §17); MockEcosystemClient.ts is a
// fixture-backed implementation for Storybook/component tests, validated
// against the same generated OpenAPI spec in CI (task B-17's contract
// test, CONTRACTS.md §16 point 2).
import type {
  Capabilities, CreateImportPayload, CreateResult, CreateWritePayload, EcosystemConfig,
  EditableContent, GateFindingRow, GateHealth, GateRun, GateRunsResponse, InstallsResponse, ItemDetail, ItemListResponse,
  ItemVersion, Job, ListItemsParams, NewVersionResult, OrgPolicy,
} from "../types";

export interface EcosystemClient {
  getConfig(product?: string): Promise<EcosystemConfig>;
  listItems(params: ListItemsParams): Promise<ItemListResponse>;
  getItem(idOrNamespace: string): Promise<ItemDetail>;
  getVersions(itemId: string): Promise<ItemVersion[]>;
  getGateRuns(itemId: string): Promise<GateRunsResponse>;
  getInstalls(itemType?: string): Promise<InstallsResponse>;
  getCapabilities(surface: string): Promise<Capabilities>;

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
  setPolicy(body: Partial<Pick<OrgPolicy, "who_can_add" | "allowed_sources" | "auto_update_default" | "allowed_licenses_shared">>): Promise<OrgPolicy>;
  getGateFindings(limit?: number): Promise<GateFindingRow[]>;
  getGateHealth(): Promise<GateHealth>;
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

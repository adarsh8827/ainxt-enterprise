// SPDX-License-Identifier: MIT
// Fetch-based EcosystemClient hitting the real /ecosystem/* surface
// (docs/ecosystem/CONTRACTS.md §17). baseUrl/product/fetchImpl are
// host-injected constructor args -- this package never imports ai-ui's own
// config.js directly, so it stays independently buildable/testable
// (task F-1's own "builds independently" requirement). ai-ui's
// Marketplace.jsx wrapper constructs this with API_BASE + credentials:
// 'include', matching every other ai-ui fetch call's existing auth
// convention (cookie session, CONTRACTS.md §14).
import type {
  AdminSourcesInfo, Capabilities, CreateImportPayload, CreateResult, CreateWritePayload, EcosystemConfig,
  EditableContent, GateFindingRow, GateHealth, GateRun, GateRunsResponse, InstallsResponse, ItemDetail, ItemListResponse,
  ItemVersion, Job, ListItemsParams, LiveSearchResult, NewVersionResult, OrgPolicy, ShardSyncStatus,
} from "../types";
import { EcosystemApiError, type EcosystemClient } from "./EcosystemClient";

export interface RealEcosystemClientOptions {
  /** e.g. "/ainxt/v1/api" -- everything under this path is the gateway's mount. */
  baseUrl: string;
  /** The x-ainxt-product header value; omit to let the backend resolve the org's primary product. */
  product?: string;
  /** Defaults to the global fetch with credentials: 'include' (cookie session, matches every other ai-ui call). */
  fetchImpl?: typeof fetch;
}

function toQuery(params: Record<string, unknown>): string {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const v of value) usp.append(`${key}[]`, String(v));
    } else {
      usp.append(key, String(value));
    }
  }
  const qs = usp.toString();
  return qs ? `?${qs}` : "";
}

export class RealEcosystemClient implements EcosystemClient {
  private readonly baseUrl: string;
  private readonly product?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: RealEcosystemClientOptions) {
    this.baseUrl = options.baseUrl;
    this.product = options.product;
    this.fetchImpl = options.fetchImpl ?? ((...args) => fetch(...args));
  }

  private async request<T>(
    path: string, init: RequestInit = {}, idempotencyKey?: string,
  ): Promise<T> {
    const headers = new Headers(init.headers);
    if (this.product) headers.set("x-ainxt-product", this.product);
    if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
    if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    const res = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers,
      credentials: "include",
      cache: "no-store",
    });

    if (res.status === 204) return undefined as T;

    const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
    const body = isJson ? await res.json().catch(() => null) : null;

    if (!res.ok) {
      const detail = body?.detail ?? body ?? {};
      throw new EcosystemApiError(
        detail.code ?? "BAD_REQUEST",
        detail.message ?? res.statusText,
        Boolean(detail.retryable),
        detail.details,
      );
    }
    return body as T;
  }

  getConfig(): Promise<EcosystemConfig> {
    return this.request<EcosystemConfig>("/ecosystem/config");
  }

  listItems(params: ListItemsParams): Promise<ItemListResponse> {
    return this.request<ItemListResponse>(`/ecosystem/items${toQuery(params as Record<string, unknown>)}`);
  }

  /** Item (d), part 2: a dedicated fetch (not routed through `request()`)
   * because a 304 response has no JSON body and isn't `res.ok` -- `request()`
   * would either throw on it or fail parsing it as an error. This reads the
   * ETag header directly and treats 304 as a genuine, non-error outcome. */
  async listItemsWithEtag(
    params: ListItemsParams, ifNoneMatch?: string | null,
  ): Promise<{ data: ItemListResponse | null; etag: string | null; notModified: boolean }> {
    const headers = new Headers();
    if (this.product) headers.set("x-ainxt-product", this.product);
    if (ifNoneMatch) headers.set("If-None-Match", ifNoneMatch);

    const res = await this.fetchImpl(`${this.baseUrl}/ecosystem/items${toQuery(params as Record<string, unknown>)}`, {
      headers,
      credentials: "include",
      cache: "no-store",
    });
    const etag = res.headers.get("ETag");

    if (res.status === 304) {
      return { data: null, etag, notModified: true };
    }

    const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
    const body = isJson ? await res.json().catch(() => null) : null;

    if (!res.ok) {
      const detail = body?.detail ?? body ?? {};
      throw new EcosystemApiError(
        detail.code ?? "BAD_REQUEST",
        detail.message ?? res.statusText,
        Boolean(detail.retryable),
        detail.details,
      );
    }
    return { data: body as ItemListResponse, etag, notModified: false };
  }

  getItem(idOrNamespace: string): Promise<ItemDetail> {
    return this.request<ItemDetail>(`/ecosystem/items/${encodeURIComponent(idOrNamespace)}`);
  }

  getVersions(itemId: string): Promise<ItemVersion[]> {
    return this.request<{ versions: ItemVersion[] }>(`/ecosystem/items/${itemId}/versions`).then((r) => r.versions);
  }

  getGateRuns(itemId: string): Promise<GateRunsResponse> {
    return this.request<GateRunsResponse>(`/ecosystem/items/${itemId}/gate-runs`);
  }

  getInstalls(itemType?: string): Promise<InstallsResponse> {
    return this.request<InstallsResponse>(`/ecosystem/installs${toQuery({ item_type: itemType })}`);
  }

  getCapabilities(surface: string): Promise<Capabilities> {
    return this.request<Capabilities>(`/ecosystem/capabilities${toQuery({ surface })}`);
  }

  searchLive(query: string): Promise<{ results: LiveSearchResult[] }> {
    return this.request<{ results: LiveSearchResult[] }>(`/ecosystem/search/live${toQuery({ q: query })}`);
  }

  createItem(payload: CreateWritePayload | CreateImportPayload, idempotencyKey: string): Promise<CreateResult> {
    return this.request<CreateResult>(
      "/ecosystem/items", { method: "POST", body: JSON.stringify(payload) }, idempotencyKey,
    );
  }

  uploadItem(form: FormData, idempotencyKey: string): Promise<CreateResult> {
    return this.request<CreateResult>(
      "/ecosystem/items/upload", { method: "POST", body: form }, idempotencyKey,
    );
  }

  uploadIcon(file: File): Promise<{ icon_url: string }> {
    const form = new FormData();
    form.append("file", file);
    return this.request<{ icon_url: string }>("/ecosystem/uploads/icon", { method: "POST", body: form });
  }

  createNewVersion(
    itemId: string, content: EditableContent, license?: string,
    tierOptions?: { licenseAcknowledged?: boolean; selfAuthored?: boolean },
  ): Promise<NewVersionResult> {
    return this.request<NewVersionResult>(
      `/ecosystem/items/${itemId}/new-version`,
      {
        method: "POST",
        body: JSON.stringify({
          content, license,
          license_acknowledged: tierOptions?.licenseAcknowledged ?? false,
          self_authored: tierOptions?.selfAuthored ?? false,
        }),
      },
    );
  }

  install(
    itemId: string, body: { version_id: string; surfaces: string[]; scope: string; origin: string },
    idempotencyKey: string,
  ): Promise<Job> {
    return this.request<Job>(
      `/ecosystem/items/${itemId}/install`, { method: "POST", body: JSON.stringify(body) }, idempotencyKey,
    );
  }

  uninstall(installId: string): Promise<void> {
    return this.request<void>(`/ecosystem/installs/${installId}/uninstall`, { method: "POST" });
  }

  setEnabled(installId: string, enabled: boolean): Promise<void> {
    return this.request<void>(
      `/ecosystem/installs/${installId}/set-enabled`, { method: "POST", body: JSON.stringify({ enabled }) },
    );
  }

  setSurfaces(installId: string, surfaces: string[]): Promise<void> {
    return this.request<void>(
      `/ecosystem/installs/${installId}/set-surfaces`, { method: "POST", body: JSON.stringify({ surfaces }) },
    );
  }

  updateInstall(installId: string, versionId: string): Promise<void> {
    return this.request<void>(
      `/ecosystem/installs/${installId}/update`, { method: "POST", body: JSON.stringify({ version_id: versionId }) },
    );
  }

  rollbackInstall(installId: string, versionId: string): Promise<void> {
    return this.request<void>(
      `/ecosystem/installs/${installId}/rollback`, { method: "POST", body: JSON.stringify({ version_id: versionId }) },
    );
  }

  shareItem(itemId: string, installId: string, sharedWithType: string, sharedWithId: string): Promise<void> {
    return this.request<void>(`/ecosystem/items/${itemId}/share`, {
      method: "POST",
      body: JSON.stringify({ install_id: installId, shared_with_type: sharedWithType, shared_with_id: sharedWithId }),
    });
  }

  unshare(shareId: string): Promise<void> {
    return this.request<void>(`/ecosystem/shares/${shareId}/unshare`, { method: "POST" });
  }

  reportItem(itemId: string, reason: string): Promise<void> {
    return this.request<void>(`/ecosystem/items/${itemId}/report`, { method: "POST", body: JSON.stringify({ reason }) });
  }

  deprecateItem(itemId: string): Promise<void> {
    return this.request<void>(`/ecosystem/items/${itemId}/deprecate`, { method: "POST" });
  }

  deleteDraft(itemId: string): Promise<void> {
    return this.request<void>(`/ecosystem/items/${itemId}/delete-draft`, { method: "POST" });
  }

  getJob(jobId: string): Promise<Job> {
    return this.request<Job>(`/ecosystem/jobs/${jobId}`);
  }

  getPolicy(): Promise<OrgPolicy> {
    return this.request<OrgPolicy>("/ecosystem/policy");
  }

  setPolicy(
    body: Partial<Pick<
      OrgPolicy,
      "who_can_add" | "allowed_sources" | "auto_update_default" | "allowed_licenses_shared"
      | "who_can_share" | "ethics_review_policy" | "gate_precheck_enabled" | "gate_precheck_cap_per_hour"
      | "live_sources_enabled"
    >>,
  ): Promise<OrgPolicy> {
    return this.request<OrgPolicy>("/ecosystem/policy", { method: "PUT", body: JSON.stringify(body) });
  }

  getGateFindings(limit?: number): Promise<GateFindingRow[]> {
    return this.request<{ findings: GateFindingRow[] }>(`/ecosystem/gate-findings${toQuery({ limit })}`).then((r) => r.findings);
  }

  getGateHealth(): Promise<GateHealth> {
    return this.request<GateHealth>("/ecosystem/admin/gate-health");
  }

  getAdminSources(): Promise<AdminSourcesInfo> {
    return this.request<AdminSourcesInfo>("/ecosystem/admin/sources");
  }

  syncCatalogNow(): Promise<{ ok: boolean; shards: ShardSyncStatus[] }> {
    return this.request<{ ok: boolean; shards: ShardSyncStatus[] }>("/ecosystem/admin/catalog-sync", { method: "POST" });
  }

  setFeatured(itemId: string, featured: boolean): Promise<void> {
    return this.request<void>(`/ecosystem/featured/${itemId}`, { method: "PUT", body: JSON.stringify({ featured }) });
  }

  clearFeaturedOverride(itemId: string): Promise<void> {
    return this.request<void>(`/ecosystem/featured/${itemId}`, { method: "DELETE" });
  }

  forceDisable(itemId: string): Promise<void> {
    return this.request<void>(`/ecosystem/items/${itemId}/force-disable`, { method: "POST" });
  }

  unyank(itemId: string): Promise<void> {
    return this.request<void>(`/ecosystem/items/${itemId}/unyank`, { method: "POST" });
  }

  requireItem(itemId: string): Promise<void> {
    return this.request<void>(`/ecosystem/items/${itemId}/require`, { method: "POST" });
  }

  unrequireItem(itemId: string): Promise<void> {
    return this.request<void>(`/ecosystem/items/${itemId}/unrequire`, { method: "POST" });
  }

  /**
   * POST /ecosystem/drafts is an SSE stream (task B-14, M5) -- not yet
   * mounted server-side (see routers/ecosystem_router.py's own header
   * comment). This throws rather than silently no-op'ing, so any M5 caller
   * finds out immediately rather than debugging a component that "does
   * nothing."
   */
  streamDraft(): { cancel: () => void } {
    throw new Error("streamDraft: POST /ecosystem/drafts is not implemented server-side yet (task B-14, M5)");
  }
}

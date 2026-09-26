// SPDX-License-Identifier: MIT
// In-memory, fixture-backed EcosystemClient for Storybook stories and
// component tests -- never used against a real backend. Validated against
// the same generated OpenAPI spec in CI (task B-17, CONTRACTS.md §16 point
// 2) so this can't silently drift from what the real backend actually
// returns.
import type {
  Capabilities, CreateImportPayload, CreateResult, CreateWritePayload, EcosystemConfig,
  GateFindingRow, GateRun, Install, InstallsResponse, ItemDetail, ItemListResponse, ItemVersion,
  Job, ListItemsParams, OrgPolicy,
} from "../types";
import { EcosystemApiError, type EcosystemClient } from "./EcosystemClient";
import { MOCK_CONFIG, MOCK_DETAILS, MOCK_ITEMS } from "./fixtures";

export interface MockEcosystemClientOptions {
  config?: EcosystemConfig;
  items?: ItemDetail[];
  /** item_ids the caller starts out with installed, e.g. the builtin item. */
  initialInstalls?: string[];
  /** Simulated network latency, ms -- 0 by default so component tests stay fast. */
  latencyMs?: number;
}

let installCounter = 0;
let jobCounter = 0;

export class MockEcosystemClient implements EcosystemClient {
  private config: EcosystemConfig;
  private items: Map<string, ItemDetail>;
  private installs: Install[] = [];
  private policy: OrgPolicy = { org_id: "mock-org", who_can_add: "all_users", allowed_sources: ["central_index"], auto_update_default: false };
  private readonly latencyMs: number;

  constructor(options: MockEcosystemClientOptions = {}) {
    this.config = options.config ?? MOCK_CONFIG;
    const seedItems = options.items ?? Object.values(MOCK_DETAILS);
    this.items = new Map(seedItems.map((i) => [i.id, i]));
    this.latencyMs = options.latencyMs ?? 0;

    for (const itemId of options.initialInstalls ?? []) {
      const detail = this.items.get(itemId);
      if (!detail) continue;
      this.installs.push({
        install_id: `install-${itemId}`, item: detail, version_id: `${itemId}-v1`, scope: "provisioned", origin: "provisioned",
        installed_by: "mock-user", installed_for: "mock-user", enabled: true,
        surfaces: ["chat"], auto_update: false, installed_at: new Date().toISOString(),
      });
    }
  }

  private async delay<T>(value: T): Promise<T> {
    if (this.latencyMs > 0) await new Promise((r) => setTimeout(r, this.latencyMs));
    return value;
  }

  private mustGetItem(idOrNamespace: string): ItemDetail {
    const byId = this.items.get(idOrNamespace);
    if (byId) return byId;
    const byNs = [...this.items.values()].find((i) => i.namespace === idOrNamespace);
    if (byNs) return byNs;
    throw new EcosystemApiError("NOT_FOUND", `no such item ${idOrNamespace}`, false);
  }

  getConfig(): Promise<EcosystemConfig> {
    return this.delay(this.config);
  }

  listItems(params: ListItemsParams): Promise<ItemListResponse> {
    let items = [...this.items.values()];
    if (params.item_type) items = items.filter((i) => i.item_type === params.item_type);
    if (params.category?.length) items = items.filter((i) => params.category!.includes(i.category));
    if (params.trust?.length) items = items.filter((i) => params.trust!.includes(i.trust_tier));
    if (params.verdict?.length) items = items.filter((i) => params.verdict!.includes(i.latest_verdict));
    if (params.q) {
      const needle = params.q.toLowerCase();
      items = items.filter((i) => i.display_name.toLowerCase().includes(needle) || i.description.toLowerCase().includes(needle));
    }
    if (!params.status?.length) items = items.filter((i) => i.status !== "yanked");
    if (params.sort === "name") items.sort((a, b) => a.display_name.localeCompare(b.display_name));
    else items.sort((a, b) => Number(b.is_featured) - Number(a.is_featured));
    return this.delay({ items, next_cursor: null, total_hint: items.length });
  }

  getItem(idOrNamespace: string): Promise<ItemDetail> {
    return this.delay(this.mustGetItem(idOrNamespace));
  }

  getVersions(itemId: string): Promise<ItemVersion[]> {
    const item = this.mustGetItem(itemId);
    return this.delay([{
      id: `${item.id}-v1`, version: item.latest_version ?? "1.0.0", pinned_sha: null,
      content_hash: "sha256:mock", license: item.license, gate_verdict: item.latest_verdict,
      created_at: new Date().toISOString(), is_current: true,
    }]);
  }

  getGateRuns(itemId: string): Promise<GateRun[]> {
    const item = this.mustGetItem(itemId);
    const findings = item.latest_verdict === "fail"
      ? [{ stage: "license" as const, severity: "block" as const, code: "LICENSE_NOT_ALLOWED", message: "GPL-3.0-only is not MIT/Apache-2.0-compatible." }]
      : item.latest_verdict === "warn"
        ? [{ stage: "static_safety" as const, severity: "warn" as const, code: "EXTERNAL_URL_REFERENCE", message: "References an external URL." }]
        : [];
    return this.delay([{
      id: `${item.id}-gate-1`, version_id: `${item.id}-v1`, trigger: "ui_add", verdict: item.latest_verdict,
      scanner_version: "2026.09.1", started_at: new Date().toISOString(), finished_at: new Date().toISOString(),
      findings,
    }]);
  }

  getInstalls(itemType?: string): Promise<InstallsResponse> {
    let installs = this.installs;
    if (itemType) installs = installs.filter((i) => i.item.item_type === itemType);
    return this.delay({ installs, legacy_items: [], has_any: installs.length > 0, next_cursor: null });
  }

  getCapabilities(surface: string): Promise<Capabilities> {
    const skills = this.installs
      .filter((i) => i.enabled && i.surfaces.includes(surface))
      .map((i) => ({
        namespace: i.item.namespace, display_name: i.item.display_name,
        description: i.item.description, slash_command: `/${i.item.namespace.split("/")[1] ?? i.item.namespace}`,
      }));
    return this.delay({ surface, skills, plugins: [], connectors: [], mcp_tools: [] });
  }

  createItem(payload: CreateWritePayload | CreateImportPayload): Promise<CreateResult> {
    const id = `mock-created-${++installCounter}`;
    const detail: ItemDetail = {
      id, namespace: payload.namespace, item_type: payload.item_type,
      display_name: "display_name" in payload ? payload.display_name : payload.namespace,
      description: "description" in payload ? payload.description : "",
      category: payload.category, tags: [], icon_url: null, trust_tier: "community",
      license: payload.license ?? "MIT", status: "active", is_featured: false, is_new: true,
      latest_version: "1.0.0", latest_verdict: "pending", allowed_actions: ["delete_draft", "report"],
      publisher: { slug: payload.namespace.split("/")[0] ?? "acme", type: "user" },
      attribution: "", source: { kind: "local", url: null }, manifest: {},
      deprecated_at: null, deprecated_by: null,
    };
    this.items.set(id, detail);
    return this.delay({ item_id: id, version_id: `${id}-v1`, gate_run_id: `${id}-gate-1`, status: "verifying", provision_scope: "private" });
  }

  uploadItem(): Promise<CreateResult> {
    return this.createItem({ create_via: "write", item_type: "skill", namespace: "mock/uploaded", display_name: "Uploaded", description: "", category: "general", content: { instructions: "", files: [] } });
  }

  uploadIcon(): Promise<{ icon_url: string }> {
    return this.delay({ icon_url: "url:/mock/icon.png" });
  }

  install(itemId: string, body: { version_id: string; surfaces: string[]; scope: string; origin: string }): Promise<Job> {
    const item = this.mustGetItem(itemId);
    const installId = `install-${++installCounter}`;
    this.installs.push({
      install_id: installId, item, version_id: body.version_id, scope: body.scope as Install["scope"], origin: body.origin as Install["origin"],
      installed_by: "mock-user", installed_for: "mock-user", enabled: true,
      surfaces: body.surfaces, auto_update: false, installed_at: new Date().toISOString(),
    });
    return this.delay({ job_id: `job-${++jobCounter}`, status: "active", item_id: itemId, version_id: body.version_id, gate_run_id: null, error: null });
  }

  uninstall(installId: string): Promise<void> {
    this.installs = this.installs.filter((i) => i.install_id !== installId);
    return this.delay(undefined);
  }

  setEnabled(installId: string, enabled: boolean): Promise<void> {
    const row = this.installs.find((i) => i.install_id === installId);
    if (row) row.enabled = enabled;
    return this.delay(undefined);
  }

  updateInstall(): Promise<void> {
    return this.delay(undefined);
  }

  rollbackInstall(): Promise<void> {
    return this.delay(undefined);
  }

  shareItem(): Promise<void> {
    return this.delay(undefined);
  }

  unshare(): Promise<void> {
    return this.delay(undefined);
  }

  reportItem(): Promise<void> {
    return this.delay(undefined);
  }

  deprecateItem(itemId: string): Promise<void> {
    const item = this.items.get(itemId);
    if (item) item.status = "deprecated";
    return this.delay(undefined);
  }

  deleteDraft(itemId: string): Promise<void> {
    this.items.delete(itemId);
    return this.delay(undefined);
  }

  getJob(jobId: string): Promise<Job> {
    return this.delay({ job_id: jobId, status: "active", item_id: null, version_id: null, gate_run_id: null, error: null });
  }

  getPolicy(): Promise<OrgPolicy> {
    return this.delay(this.policy);
  }

  setPolicy(body: Partial<Pick<OrgPolicy, "who_can_add" | "allowed_sources" | "auto_update_default">>): Promise<OrgPolicy> {
    this.policy = { ...this.policy, ...body };
    return this.delay(this.policy);
  }

  getGateFindings(): Promise<GateFindingRow[]> {
    return this.delay(
      [...this.items.values()]
        .filter((i) => i.latest_verdict === "fail" || i.latest_verdict === "warn")
        .map((i) => ({
          gate_run_id: `${i.id}-gate-1`, item_id: i.id, version_id: `${i.id}-v1`, trigger: "ui_add" as const,
          verdict: i.latest_verdict, started_at: new Date().toISOString(),
          findings: [{ stage: "license" as const, severity: "warn" as const, code: "MOCK_FINDING", message: "mock finding" }],
        })),
    );
  }

  setFeatured(itemId: string, featured: boolean): Promise<void> {
    const item = this.items.get(itemId);
    if (item) item.is_featured = featured;
    return this.delay(undefined);
  }

  clearFeaturedOverride(): Promise<void> {
    // The mock has no separate platform-level-vs-override distinction to
    // revert to -- a no-op is the correct mock behavior here.
    return this.delay(undefined);
  }

  forceDisable(itemId: string): Promise<void> {
    const item = this.items.get(itemId);
    if (item) item.status = "yanked";
    return this.delay(undefined);
  }

  unyank(itemId: string): Promise<void> {
    const item = this.items.get(itemId);
    if (item) item.status = "active";
    return this.delay(undefined);
  }

  requireItem(): Promise<void> {
    return this.delay(undefined);
  }

  unrequireItem(): Promise<void> {
    return this.delay(undefined);
  }

  streamDraft(_itemType: string, _intent: string, onTurn: (turn: unknown) => void): { cancel: () => void } {
    let cancelled = false;
    const steps = ["intent", "clarify", "blueprint", "content", "critique"];
    let i = 0;
    const tick = () => {
      if (cancelled || i >= steps.length) return;
      onTurn({ stage: steps[i], text: `mock ${steps[i]} turn` });
      i += 1;
      setTimeout(tick, 10);
    };
    setTimeout(tick, 10);
    return { cancel: () => { cancelled = true; } };
  }
}

export { MOCK_ITEMS };

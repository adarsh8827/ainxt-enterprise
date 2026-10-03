// SPDX-License-Identifier: MIT
// Fetch-based EcosystemClient hitting the real /ecosystem/* surface
// (docs/ecosystem/CONTRACTS.md §17). baseUrl/product/fetchImpl are
// host-injected constructor args -- this package never imports ai-ui's own
// config.js directly, so it stays independently buildable/testable
// (task F-1's own "builds independently" requirement). ai-ui's
// Marketplace.jsx wrapper constructs this with API_BASE + credentials:
// 'include', matching every other ai-ui fetch call's existing auth
// convention (cookie session, CONTRACTS.md §14).

import { EcosystemApiError } from "./EcosystemClient";
function toQuery(params) {
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
export class RealEcosystemClient {
  constructor(options) {
    this.baseUrl = options.baseUrl;
    this.product = options.product;
    this.fetchImpl = options.fetchImpl ?? ((...args) => fetch(...args));
  }
  async request(path, init = {}, idempotencyKey) {
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
      cache: "no-store"
    });
    if (res.status === 204) return undefined;
    const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
    const body = isJson ? await res.json().catch(() => null) : null;
    if (!res.ok) {
      const detail = body?.detail ?? body ?? {};
      throw new EcosystemApiError(detail.code ?? "BAD_REQUEST", detail.message ?? res.statusText, Boolean(detail.retryable), detail.details);
    }
    return body;
  }
  getConfig() {
    return this.request("/ecosystem/config");
  }
  listItems(params) {
    return this.request(`/ecosystem/items${toQuery(params)}`);
  }

  /** Item (d), part 2: a dedicated fetch (not routed through `request()`)
   * because a 304 response has no JSON body and isn't `res.ok` -- `request()`
   * would either throw on it or fail parsing it as an error. This reads the
   * ETag header directly and treats 304 as a genuine, non-error outcome. */
  async listItemsWithEtag(params, ifNoneMatch) {
    const headers = new Headers();
    if (this.product) headers.set("x-ainxt-product", this.product);
    if (ifNoneMatch) headers.set("If-None-Match", ifNoneMatch);
    const res = await this.fetchImpl(`${this.baseUrl}/ecosystem/items${toQuery(params)}`, {
      headers,
      credentials: "include",
      cache: "no-store"
    });
    const etag = res.headers.get("ETag");
    if (res.status === 304) {
      return {
        data: null,
        etag,
        notModified: true
      };
    }
    const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
    const body = isJson ? await res.json().catch(() => null) : null;
    if (!res.ok) {
      const detail = body?.detail ?? body ?? {};
      throw new EcosystemApiError(detail.code ?? "BAD_REQUEST", detail.message ?? res.statusText, Boolean(detail.retryable), detail.details);
    }
    return {
      data: body,
      etag,
      notModified: false
    };
  }
  getItem(idOrNamespace) {
    return this.request(`/ecosystem/items/${encodeURIComponent(idOrNamespace)}`);
  }
  getVersions(itemId) {
    return this.request(`/ecosystem/items/${itemId}/versions`).then(r => r.versions);
  }
  getGateRuns(itemId) {
    return this.request(`/ecosystem/items/${itemId}/gate-runs`);
  }
  getInstalls(itemType) {
    return this.request(`/ecosystem/installs${toQuery({
      item_type: itemType
    })}`);
  }
  getCapabilities(surface) {
    return this.request(`/ecosystem/capabilities${toQuery({
      surface
    })}`);
  }
  searchLive(query) {
    return this.request(`/ecosystem/search/live${toQuery({
      q: query
    })}`);
  }
  createItem(payload, idempotencyKey) {
    return this.request("/ecosystem/items", {
      method: "POST",
      body: JSON.stringify(payload)
    }, idempotencyKey);
  }
  uploadItem(form, idempotencyKey) {
    return this.request("/ecosystem/items/upload", {
      method: "POST",
      body: form
    }, idempotencyKey);
  }
  uploadIcon(file) {
    const form = new FormData();
    form.append("file", file);
    return this.request("/ecosystem/uploads/icon", {
      method: "POST",
      body: form
    });
  }
  createNewVersion(itemId, content, license, tierOptions) {
    return this.request(`/ecosystem/items/${itemId}/new-version`, {
      method: "POST",
      body: JSON.stringify({
        content,
        license,
        license_acknowledged: tierOptions?.licenseAcknowledged ?? false,
        self_authored: tierOptions?.selfAuthored ?? false
      })
    });
  }
  install(itemId, body, idempotencyKey) {
    return this.request(`/ecosystem/items/${itemId}/install`, {
      method: "POST",
      body: JSON.stringify(body)
    }, idempotencyKey);
  }
  uninstall(installId) {
    return this.request(`/ecosystem/installs/${installId}/uninstall`, {
      method: "POST"
    });
  }
  setEnabled(installId, enabled) {
    return this.request(`/ecosystem/installs/${installId}/set-enabled`, {
      method: "POST",
      body: JSON.stringify({
        enabled
      })
    });
  }
  setSurfaces(installId, surfaces) {
    return this.request(`/ecosystem/installs/${installId}/set-surfaces`, {
      method: "POST",
      body: JSON.stringify({
        surfaces
      })
    });
  }
  updateInstall(installId, versionId) {
    return this.request(`/ecosystem/installs/${installId}/update`, {
      method: "POST",
      body: JSON.stringify({
        version_id: versionId
      })
    });
  }
  rollbackInstall(installId, versionId) {
    return this.request(`/ecosystem/installs/${installId}/rollback`, {
      method: "POST",
      body: JSON.stringify({
        version_id: versionId
      })
    });
  }
  shareItem(itemId, installId, sharedWithType, sharedWithId) {
    return this.request(`/ecosystem/items/${itemId}/share`, {
      method: "POST",
      body: JSON.stringify({
        install_id: installId,
        shared_with_type: sharedWithType,
        shared_with_id: sharedWithId
      })
    });
  }
  unshare(shareId) {
    return this.request(`/ecosystem/shares/${shareId}/unshare`, {
      method: "POST"
    });
  }
  reportItem(itemId, reason) {
    return this.request(`/ecosystem/items/${itemId}/report`, {
      method: "POST",
      body: JSON.stringify({
        reason
      })
    });
  }
  deprecateItem(itemId) {
    return this.request(`/ecosystem/items/${itemId}/deprecate`, {
      method: "POST"
    });
  }
  deleteDraft(itemId) {
    return this.request(`/ecosystem/items/${itemId}/delete-draft`, {
      method: "POST"
    });
  }
  getJob(jobId) {
    return this.request(`/ecosystem/jobs/${jobId}`);
  }
  getPolicy() {
    return this.request("/ecosystem/policy");
  }
  setPolicy(body) {
    return this.request("/ecosystem/policy", {
      method: "PUT",
      body: JSON.stringify(body)
    });
  }
  getGateFindings(limit) {
    return this.request(`/ecosystem/gate-findings${toQuery({
      limit
    })}`).then(r => r.findings);
  }
  getGateHealth() {
    return this.request("/ecosystem/admin/gate-health");
  }
  getAdminSources() {
    return this.request("/ecosystem/admin/sources");
  }
  syncCatalogNow() {
    return this.request("/ecosystem/admin/catalog-sync", {
      method: "POST"
    });
  }
  setFeatured(itemId, featured) {
    return this.request(`/ecosystem/featured/${itemId}`, {
      method: "PUT",
      body: JSON.stringify({
        featured
      })
    });
  }
  clearFeaturedOverride(itemId) {
    return this.request(`/ecosystem/featured/${itemId}`, {
      method: "DELETE"
    });
  }
  forceDisable(itemId) {
    return this.request(`/ecosystem/items/${itemId}/force-disable`, {
      method: "POST"
    });
  }
  unyank(itemId) {
    return this.request(`/ecosystem/items/${itemId}/unyank`, {
      method: "POST"
    });
  }
  requireItem(itemId) {
    return this.request(`/ecosystem/items/${itemId}/require`, {
      method: "POST"
    });
  }
  unrequireItem(itemId) {
    return this.request(`/ecosystem/items/${itemId}/unrequire`, {
      method: "POST"
    });
  }

  /**
   * POST /ecosystem/drafts is an SSE stream (task B-14, M5) -- not yet
   * mounted server-side (see routers/ecosystem_router.py's own header
   * comment). This throws rather than silently no-op'ing, so any M5 caller
   * finds out immediately rather than debugging a component that "does
   * nothing."
   */
  streamDraft() {
    throw new Error("streamDraft: POST /ecosystem/drafts is not implemented server-side yet (task B-14, M5)");
  }

  /** Install-state-consistency round (2026-09-29): GET /ecosystem/events/
   * stream is a real, already-existing SSE relay of the per-org
   * `ecosystem.changed` Redis pub/sub (routers/ecosystem_events_router.py,
   * CONTRACTS.md §13) -- ai-ui's chat "/" menu already consumes it this
   * same way (useEcosystemChatSkills.js) for the identical "a plain
   * EventSource can't carry this client's own auth" reason (cookie
   * session here, but this package's own RealEcosystemClient always uses
   * `credentials: 'include'` via `this.fetchImpl` -- reusing that instead
   * of introducing a second auth path). `onEvent` fires once per real
   * "data: ..." frame (the initial ": connected" comment and periodic
   * ": ping" keep-alives are filtered out, same as ai-ui's own
   * useEcosystemChatSkills.js) -- never parses the payload itself, since
   * no consumer of this method needs a specific field out of it, only
   * "something happened, go check." */
  streamChanges(onEvent) {
    const controller = new AbortController();
    let cancelled = false;
    (async () => {
      try {
        const res = await this.fetchImpl(`${this.baseUrl}/ecosystem/events/stream`, {
          credentials: "include",
          cache: "no-store",
          signal: controller.signal
        });
        if (!res.ok || !res.body) return;
        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8", {
          fatal: false
        });
        let buffer = "";
        while (!cancelled) {
          const {
            done,
            value
          } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, {
            stream: true
          });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() ?? "";
          for (const part of parts) {
            // Same filter as ai-ui's own useEcosystemChatSkills.js --
            // skip ": connected"/": ping" keep-alive comment lines, only
            // a real "data: ..." frame is an actual ecosystem.changed
            // event worth refetching for.
            if (!part.trim().startsWith("data: ")) continue;
            onEvent();
          }
        }
      } catch {
        // Stream drop/abort -- never fatal; the caller's own next mount
        // (or a manual refresh) still gets current state via a normal GET.
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }

  // ── Connectors phase ─────────────────────────────────────────────────
  listConnections() {
    return this.request("/ecosystem/connections").then(r => r.connections);
  }
  connect(connectorRef) {
    return this.request(`/ecosystem/connections/${encodeURIComponent(connectorRef)}/connect`, {
      method: "POST"
    });
  }
  completeOAuthCallback(connectorRef, code, state) {
    return this.request(`/ecosystem/connections/${encodeURIComponent(connectorRef)}/oauth-callback`, {
      method: "POST",
      body: JSON.stringify({
        code,
        state
      })
    });
  }
  disconnect(connectorRef) {
    return this.request(`/ecosystem/connections/${encodeURIComponent(connectorRef)}/disconnect`, {
      method: "POST"
    });
  }
  reconnect(connectorRef) {
    return this.request(`/ecosystem/connections/${encodeURIComponent(connectorRef)}/reconnect`, {
      method: "POST"
    });
  }
  listOAuthApps() {
    return this.request("/ecosystem/admin/oauth-apps").then(r => r.apps);
  }
  createOAuthApp(body) {
    return this.request("/ecosystem/admin/oauth-apps", {
      method: "POST",
      body: JSON.stringify(body)
    });
  }
  deleteOAuthApp(id) {
    return this.request(`/ecosystem/admin/oauth-apps/${id}`, {
      method: "DELETE"
    });
  }
  listPendingToolCalls() {
    return this.request("/ecosystem/tool-calls/pending").then(r => r.pending);
  }
  approveToolCall(id) {
    return this.request(`/ecosystem/tool-calls/${id}/approve`, {
      method: "POST"
    });
  }
  denyToolCall(id) {
    return this.request(`/ecosystem/tool-calls/${id}/deny`, {
      method: "POST"
    });
  }
  composePlugin(itemId, parts) {
    return this.request(`/ecosystem/items/${encodeURIComponent(itemId)}/plugin-compose`, {
      method: "POST",
      body: JSON.stringify({
        parts
      })
    });
  }
  listMcpRuntimeInstances() {
    return this.request("/ecosystem/admin/mcp-runtime").then(r => r.instances);
  }
}
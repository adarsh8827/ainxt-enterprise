// SPDX-License-Identifier: MIT
// Advanced: MCP servers sub-view (docs/ecosystem/CONNECTORS_PHASE_PLAN.md
// §1 items 6-7) -- admin/dev-only, policy-gated. Custom remote MCP URL
// add form + a read-only local/stdio server list (the actual lifecycle
// worker is a separate Stage 3 backend piece; this renders whatever
// status/logs it reports, once that exists).
//
// Connectors phase item 6 (follow-up round): the add-form previously
// called `client.connect(url)` -- wrong endpoint entirely. `connect()`
// (POST /ecosystem/connections/{connector_ref}/connect) only works for an
// EXISTING connector/mcp_server item's own namespace; a brand-new custom
// URL has no such item yet. The real path (confirmed in Stage 3: gate
// stage 7 / mcp_connector_stage.py already runs its SSRF/HTTPS checks
// against whatever manifest.server_url a "write" item carries) is
// `client.createItem()` with item_type: "mcp_server" and
// content.server_url set -- the exact same POST /ecosystem/items path
// Skills' own Write flow (CreateForm.tsx) already uses, just a different
// item_type + manifest shape. No new endpoint, reused as-is.
import { useMemo, useState } from "react";
import type { CreateWritePayload } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { useConfig } from "../../hooks/useEcosystemConfig";

// Fast, client-side-only UX checks -- NOT the real security boundary
// (that's server-side: import_adapters/ssrf_guard.py's
// assert_safe_https_url(), enforced by gate stage 7 on every submission
// regardless of what this function decides). This just avoids a round
// trip + a multi-second "verifying" wait for the most obvious mistakes
// (http://, a bare IP, "localhost").
const PRIVATE_HOSTNAME_RE = /^(localhost|127\.|0\.0\.0\.0|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|169\.254\.|\[?::1\]?$|\[?fc|\[?fd)/i;

export function preValidateMcpServerUrl(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return "Enter a URL.";
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return "That doesn't look like a valid URL.";
  }
  if (parsed.protocol !== "https:") {
    return "Only https:// URLs are allowed.";
  }
  if (PRIVATE_HOSTNAME_RE.test(parsed.hostname)) {
    return "That looks like a private/internal address, which can't be reached from here.";
  }
  return null;
}

function namespaceFromUrl(url: URL, prefix: string): string {
  const hostSlug = url.hostname.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const short = Math.random().toString(36).slice(2, 8);
  return `${prefix}/mcp-${hostSlug || "server"}-${short}`;
}

export function AdvancedMcpServers({ localServers = [] }: {
  localServers?: Array<{ name: string; status: string; last_health_check: string | null }>;
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addedId, setAddedId] = useState<string | null>(null);

  const validationError = useMemo(() => (url.trim() ? preValidateMcpServerUrl(url) : null), [url]);

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const preError = preValidateMcpServerUrl(url);
    if (preError) {
      setError(preError);
      return;
    }
    const parsed = new URL(url.trim());
    const namespace = namespaceFromUrl(parsed, config.caller_default_namespace_prefix || "org");
    const payload: CreateWritePayload = {
      create_via: "write",
      item_type: "mcp_server",
      namespace,
      display_name: parsed.hostname,
      description: `Custom MCP server at ${parsed.hostname}`,
      category: config.taxonomy.categories[0] ?? "dev-tools",
      license: "MIT",
      content: { instructions: "", files: [], server_url: url.trim() },
    };
    setBusy(true);
    setError(null);
    setAddedId(null);
    client.createItem(payload, `advanced-mcp-${namespace}-${Date.now()}`)
      .then((result) => {
        setUrl("");
        setAddedId(result.item_id);
        // A "blocked" gate verdict for an obviously-bad URL server-caught
        // case (SSRF guard rejects a hostname this component's own
        // pre-check didn't catch, e.g. a redirect or DNS-level surprise)
        // surfaces as status "blocked" on the SAME create response the
        // async gate envelope already returns (CONTRACTS.md §5) -- no
        // separate poll needed for the common case; the caller can still
        // open the item's own Detail/Verification tab for the full finding.
        if (result.status === "blocked") {
          setError("This server was blocked by a safety check (invalid or unreachable address). Open its detail page for the full reason.");
        }
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Couldn't add this MCP server."))
      .finally(() => setBusy(false));
  };

  return (
    <div data-testid="advanced-mcp-servers">
      <h3 style={{ fontSize: "var(--eco-font-sizeMd)", color: "var(--eco-color-textPrimary)" }}>Add a custom MCP server</h3>
      <form onSubmit={handleAdd} style={{ display: "flex", gap: "var(--eco-space-sm)" }}>
        <input
          data-testid="advanced-mcp-url-input"
          type="url"
          placeholder="https://example.com/mcp"
          value={url}
          onChange={(e) => { setUrl(e.target.value); setError(null); }}
          aria-invalid={Boolean(validationError)}
          style={{ flex: 1, padding: "8px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)" }}
        />
        <button type="submit" data-testid="advanced-mcp-add" disabled={busy || Boolean(validationError)}>{busy ? "Adding…" : "Add"}</button>
      </form>
      {validationError && !error && (
        <p data-testid="advanced-mcp-validation-error" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeSm)" }}>{validationError}</p>
      )}
      {error && <p data-testid="advanced-mcp-error" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeSm)" }}>{error}</p>}
      {addedId && !error && (
        <p data-testid="advanced-mcp-added" style={{ color: "var(--eco-color-textSecondary)", fontSize: "var(--eco-font-sizeSm)" }}>
          Added -- verifying now.
        </p>
      )}

      <h3 style={{ fontSize: "var(--eco-font-sizeMd)", color: "var(--eco-color-textPrimary)", marginTop: "var(--eco-space-lg)" }}>Local / stdio servers</h3>
      <ul data-testid="advanced-mcp-local-list" style={{ listStyle: "none", padding: 0 }}>
        {localServers.map((s) => (
          <li key={s.name} data-testid="advanced-mcp-local-row" style={{ display: "flex", justifyContent: "space-between", padding: "var(--eco-space-sm) 0", borderBottom: "1px solid var(--eco-color-border)" }}>
            <span>{s.name}</span>
            <span data-status={s.status}>{s.status}</span>
          </li>
        ))}
        {localServers.length === 0 && (
          <li style={{ color: "var(--eco-color-textMuted)", fontSize: "var(--eco-font-sizeSm)" }}>No local MCP servers running.</li>
        )}
      </ul>
    </div>
  );
}

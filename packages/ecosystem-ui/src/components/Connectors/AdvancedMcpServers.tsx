// SPDX-License-Identifier: MIT
// Advanced: MCP servers sub-view (docs/ecosystem/CONNECTORS_PHASE_PLAN.md
// §1 items 6-7) -- admin/dev-only, policy-gated. Custom remote MCP URL
// add form + a read-only local/stdio server list (the actual lifecycle
// worker is a separate Stage 3 backend piece; this renders whatever
// status/logs it reports, once that exists).
import { useState } from "react";
import { useEcosystemClient } from "../../context/HostContext";

export function AdvancedMcpServers({ localServers = [] }: {
  localServers?: Array<{ name: string; status: string; last_health_check: string | null }>;
}) {
  const client = useEcosystemClient();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    client.connect(url.trim())
      .then(() => setUrl(""))
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
          onChange={(e) => setUrl(e.target.value)}
          style={{ flex: 1, padding: "8px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)" }}
        />
        <button type="submit" data-testid="advanced-mcp-add" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
      </form>
      {error && <p style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeSm)" }}>{error}</p>}

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

// SPDX-License-Identifier: MIT
// Side-panel "Connectors & tools" risk summary for a plugin (docs/
// ecosystem/PLUGINS_PHASE_PLAN.md §4). manifest.parts only carries
// {namespace, display_name} per part (no tool/classification data inline)
// -- this fetches each bundled connector/mcp_server part's own ItemDetail
// to read its real manifest.tools, the same shape ConnectorDetail.tsx
// already reads. Best-effort: a part that fails to fetch (deleted,
// no permission, etc.) is silently excluded from the tally rather than
// failing the whole panel -- this is a plain-language summary, not an
// audit trail.
import { useEffect, useState } from "react";
import type { ConnectorTool, PluginParts, ToolClassification } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { ToolClassificationBadge } from "../Connectors/ToolClassificationBadge";

type Tally = Record<ToolClassification, number>;
const EMPTY_TALLY: Tally = { read: 0, write: 0, destructive: 0 };

export function PluginRiskSummary({ parts }: { parts: PluginParts }) {
  const client = useEcosystemClient();
  const [tally, setTally] = useState<Tally | null>(null);
  const connectorRefs = [...parts.connectors, ...parts.mcp_servers];

  useEffect(() => {
    if (connectorRefs.length === 0) { setTally(EMPTY_TALLY); return; }
    let alive = true;
    Promise.allSettled(connectorRefs.map((ref) => client.getItem(ref.namespace))).then((results) => {
      if (!alive) return;
      const next = { ...EMPTY_TALLY };
      for (const result of results) {
        if (result.status !== "fulfilled") continue;
        const tools = (result.value.manifest?.tools as ConnectorTool[] | undefined) ?? [];
        for (const tool of tools) next[tool.classification] += 1;
      }
      setTally(next);
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectorRefs.map((r) => r.namespace).join(",")]);

  if (connectorRefs.length === 0) {
    return (
      <div data-testid="plugin-risk-summary" style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textMuted)" }}>
        This plugin doesn&apos;t bundle any connectors or MCP servers.
      </div>
    );
  }

  return (
    <div data-testid="plugin-risk-summary" style={{ fontSize: "var(--eco-font-sizeSm)" }}>
      <p style={{ color: "var(--eco-color-textSecondary)", margin: "0 0 var(--eco-space-sm)" }}>
        Bundles {parts.connectors.length} connector{parts.connectors.length === 1 ? "" : "s"} and{" "}
        {parts.mcp_servers.length} MCP server{parts.mcp_servers.length === 1 ? "" : "s"}. Each still needs its own
        sign-in before its tools can be used.
      </p>
      {tally === null ? (
        <span data-testid="plugin-risk-summary-loading" style={{ color: "var(--eco-color-textMuted)" }}>Checking tools…</span>
      ) : (
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          {(["destructive", "write", "read"] as ToolClassification[]).filter((c) => tally[c] > 0).map((c) => (
            <span key={c} data-testid="plugin-risk-summary-count" style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
              <ToolClassificationBadge classification={c} /> × {tally[c]}
            </span>
          ))}
          {tally.read + tally.write + tally.destructive === 0 && <span style={{ color: "var(--eco-color-textMuted)" }}>No tools listed yet.</span>}
        </div>
      )}
    </div>
  );
}

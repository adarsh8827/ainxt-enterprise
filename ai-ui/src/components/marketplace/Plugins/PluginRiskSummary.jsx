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
import { useEcosystemClient } from "../lib/context/HostContext";
import { ToolClassificationBadge } from "../Connectors/ToolClassificationBadge";
const EMPTY_TALLY = {
  read: 0,
  write: 0,
  destructive: 0
};
export function PluginRiskSummary({
  parts
}) {
  const client = useEcosystemClient();
  const [tally, setTally] = useState(null);
  const connectorRefs = [...parts.connectors, ...parts.mcp_servers];
  useEffect(() => {
    if (connectorRefs.length === 0) {
      setTally(EMPTY_TALLY);
      return;
    }
    let alive = true;
    Promise.allSettled(connectorRefs.map(ref => client.getItem(ref.namespace))).then(results => {
      if (!alive) return;
      const next = {
        ...EMPTY_TALLY
      };
      for (const result of results) {
        if (result.status !== "fulfilled") continue;
        const tools = result.value.manifest?.tools ?? [];
        for (const tool of tools) next[tool.classification] += 1;
      }
      setTally(next);
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectorRefs.map(r => r.namespace).join(",")]);
  if (connectorRefs.length === 0) {
    return <div data-testid="plugin-risk-summary" className="text-sm text-gray-400">
        This plugin doesn&apos;t bundle any connectors or MCP servers.
      </div>;
  }
  return <div data-testid="plugin-risk-summary" className="text-sm">
      <p className="text-gray-500 mt-0 mb-2">
        Bundles {parts.connectors.length} connector{parts.connectors.length === 1 ? "" : "s"} and{" "}
        {parts.mcp_servers.length} MCP server{parts.mcp_servers.length === 1 ? "" : "s"}. Each still needs its own
        sign-in before its tools can be used.
      </p>
      {tally === null ? <span data-testid="plugin-risk-summary-loading" className="text-gray-400">Checking tools…</span> : <div className="flex gap-2 flex-wrap">
          {["destructive", "write", "read"].filter(c => tally[c] > 0).map(c => <span key={c} data-testid="plugin-risk-summary-count" className="inline-flex items-center gap-1">
              <ToolClassificationBadge classification={c} /> × {tally[c]}
            </span>)}
          {tally.read + tally.write + tally.destructive === 0 && <span className="text-gray-400">No tools listed yet.</span>}
        </div>}
    </div>;
}
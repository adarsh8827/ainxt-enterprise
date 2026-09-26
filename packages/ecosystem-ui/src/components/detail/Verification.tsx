// SPDX-License-Identifier: MIT
// Task F-7: real Verification tab over GET /ecosystem/items/{id}/gate-runs
// (task B-8/B-9's 7 stages) -- replaces the merged FE's 4 static
// always-passing checks (CONFIG_AND_PRODUCTS.md §7 item 13's removal).
import { useEffect, useState } from "react";
import type { GateRun } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { VerdictBadge } from "../Badges";

const STAGE_LABELS: Record<string, string> = {
  manifest: "Manifest", license: "License", static_safety: "Static safety",
  supply_chain: "Supply chain", sandbox: "Sandbox", ethics: "Ethics review", mcp_connector: "MCP/connector",
};

export function Verification({ itemId }: { itemId: string }) {
  const client = useEcosystemClient();
  const [runs, setRuns] = useState<GateRun[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    client.getGateRuns(itemId).then((r) => { if (!cancelled) setRuns(r); });
    return () => { cancelled = true; };
  }, [client, itemId]);

  if (runs === null) return <div data-testid="detail-tab-verification-loading">Loading verification history…</div>;
  if (runs.length === 0) return <div data-testid="detail-tab-verification-empty">No verification runs yet.</div>;

  const latest = runs[0]!;
  return (
    <div data-testid="detail-tab-verification">
      <div style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", marginBottom: "var(--eco-space-md)" }}>
        <VerdictBadge verdict={latest.verdict} />
        <span style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)" }}>scanner {latest.scanner_version}</span>
      </div>
      {latest.findings.length === 0 ? (
        <p style={{ color: "var(--eco-color-textSecondary)" }}>No findings.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0 }}>
          {latest.findings.map((f, i) => (
            <li
              key={i}
              data-testid="gate-finding"
              data-severity={f.severity}
              style={{
                padding: "var(--eco-space-sm)", marginBottom: "var(--eco-space-sm)",
                borderRadius: "var(--eco-radius-md)",
                background: f.severity === "block" ? "var(--eco-color-dangerBg)" : "var(--eco-color-warningBg)",
                color: f.severity === "block" ? "var(--eco-color-danger)" : "var(--eco-color-warning)",
              }}
            >
              <strong>{STAGE_LABELS[f.stage] ?? f.stage}</strong> — {f.code}
              <div style={{ fontSize: "var(--eco-font-sizeSm)" }}>{f.message}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

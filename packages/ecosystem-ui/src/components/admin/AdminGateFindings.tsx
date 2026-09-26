// SPDX-License-Identifier: MIT
// Task F-13: dashboard over GET /ecosystem/gate-findings (org-scoped --
// see gate_service.list_recent_findings()'s own cross-org isolation test).
import { useEffect, useState } from "react";
import type { GateFindingRow } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { VerdictBadge } from "../Badges";

export function AdminGateFindings() {
  const client = useEcosystemClient();
  const [rows, setRows] = useState<GateFindingRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    client.getGateFindings(100).then((r) => { if (!cancelled) setRows(r); }).catch((e) => setError(String(e)));
    return () => { cancelled = true; };
  }, [client]);

  if (error) return <div role="alert" data-testid="admin-gate-findings-error">{error}</div>;
  if (rows === null) return <div data-testid="admin-gate-findings-loading">Loading…</div>;
  if (rows.length === 0) return <div data-testid="admin-gate-findings-empty">No findings recorded.</div>;

  return (
    <div data-testid="admin-gate-findings">
      <h2 style={{ color: "var(--eco-color-textPrimary)" }}>Gate findings</h2>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--eco-font-sizeSm)" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--eco-color-textSecondary)" }}>
            <th>Item</th><th>Verdict</th><th>Trigger</th><th>Started</th><th>Findings</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.gate_run_id} data-testid="admin-gate-findings-row" style={{ borderTop: "1px solid var(--eco-color-border)" }}>
              <td style={{ fontFamily: "monospace", color: "var(--eco-color-textPrimary)" }}>{row.item_id}</td>
              <td><VerdictBadge verdict={row.verdict} /></td>
              <td style={{ color: "var(--eco-color-textSecondary)" }}>{row.trigger}</td>
              <td style={{ color: "var(--eco-color-textMuted)" }}>{row.started_at ? new Date(row.started_at).toLocaleString() : "—"}</td>
              <td style={{ color: "var(--eco-color-textSecondary)" }}>{row.findings.map((f) => f.code).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

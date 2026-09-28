// SPDX-License-Identifier: MIT
// Task F-13: dashboard over GET /ecosystem/gate-findings (org-scoped --
// see gate_service.list_recent_findings()'s own cross-org isolation test).
import { useEffect, useState } from "react";
import type { GateFindingRow, GateHealth } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { VerdictBadge } from "../Badges";

/** Item 8: gate_health_service.get_health() already computed this signal
 * (no heartbeat within heartbeat_stale_after_seconds, or a stuck-verifying
 * backlog) -- it was just never surfaced anywhere in the UI. Polled, not
 * fetched once, since "gate worker just went down" is exactly the kind of
 * thing an admin watching this screen should see without a manual refresh. */
function GateHealthBanner() {
  const client = useEcosystemClient();
  const [health, setHealth] = useState<GateHealth | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = () => client.getGateHealth().then((h) => { if (!cancelled) setHealth(h); }).catch(() => {});
    poll();
    const interval = setInterval(poll, 30_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [client]);

  if (!health || !health.message) return null;

  return (
    <div
      role="alert"
      data-testid="admin-gate-health-warning"
      style={{
        background: "var(--eco-color-warningBg)", color: "var(--eco-color-warning)",
        padding: "var(--eco-space-sm) var(--eco-space-md)", borderRadius: "var(--eco-radius-md)",
        marginBottom: "var(--eco-space-md)", fontSize: "var(--eco-font-sizeSm)",
      }}
    >
      {health.gate_worker_healthy
        ? <><strong>Gate queue backed up:</strong> {health.message}</>
        : <><strong>Gate worker not running:</strong> {health.message}</>}
    </div>
  );
}

export function AdminGateFindings() {
  const client = useEcosystemClient();
  const [rows, setRows] = useState<GateFindingRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    client.getGateFindings(100).then((r) => { if (!cancelled) setRows(r); }).catch((e) => setError(String(e)));
    return () => { cancelled = true; };
  }, [client]);

  if (error) return <><GateHealthBanner /><div role="alert" data-testid="admin-gate-findings-error">{error}</div></>;
  if (rows === null) return <><GateHealthBanner /><div data-testid="admin-gate-findings-loading">Loading…</div></>;
  if (rows.length === 0) return <><GateHealthBanner /><div data-testid="admin-gate-findings-empty">No findings recorded.</div></>;

  return (
    <div data-testid="admin-gate-findings">
      <GateHealthBanner />
      <h2 style={{ fontSize: "var(--eco-font-sizeXl)", color: "var(--eco-color-textPrimary)" }}>Gate findings</h2>
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

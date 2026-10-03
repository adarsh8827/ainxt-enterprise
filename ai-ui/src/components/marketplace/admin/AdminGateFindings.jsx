// SPDX-License-Identifier: MIT
// Task F-13: dashboard over GET /ecosystem/gate-findings (org-scoped --
// see gate_service.list_recent_findings()'s own cross-org isolation test).
import { useEffect, useState } from "react";
import { useEcosystemClient } from "../lib/context/HostContext";
import { VerdictBadge } from "../Badges";

/** Item 8: gate_health_service.get_health() already computed this signal
 * (no heartbeat within heartbeat_stale_after_seconds, or a stuck-verifying
 * backlog) -- it was just never surfaced anywhere in the UI. Polled, not
 * fetched once, since "gate worker just went down" is exactly the kind of
 * thing an admin watching this screen should see without a manual refresh. */
function GateHealthBanner() {
  const client = useEcosystemClient();
  const [health, setHealth] = useState(null);
  useEffect(() => {
    let cancelled = false;
    const poll = () => client.getGateHealth().then(h => {
      if (!cancelled) setHealth(h);
    }).catch(() => {});
    poll();
    const interval = setInterval(poll, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [client]);
  if (!health || !health.message) return null;
  return <div role="alert" data-testid="admin-gate-health-warning" className="bg-amber-50 text-amber-700 px-4 py-2 rounded-md mb-4 text-sm">
      {health.gate_worker_healthy ? <><strong>Gate queue backed up:</strong> {health.message}</> : <><strong>Gate worker not running:</strong> {health.message}</>}
    </div>;
}
export function AdminGateFindings() {
  const client = useEcosystemClient();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let cancelled = false;
    client.getGateFindings(100).then(r => {
      if (!cancelled) setRows(r);
    }).catch(e => setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [client]);
  if (error) return <><GateHealthBanner /><div role="alert" data-testid="admin-gate-findings-error">{error}</div></>;
  if (rows === null) return <><GateHealthBanner /><div data-testid="admin-gate-findings-loading">Loading…</div></>;
  if (rows.length === 0) return <><GateHealthBanner /><div data-testid="admin-gate-findings-empty">No findings recorded.</div></>;
  return <div data-testid="admin-gate-findings">
      <GateHealthBanner />
      <h2 className="text-xl text-gray-900">Gate findings</h2>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="text-left text-gray-500">
            <th>Item</th><th>Verdict</th><th>Trigger</th><th>Started</th><th>Findings</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => <tr key={row.gate_run_id} data-testid="admin-gate-findings-row" className="border-t border-gray-200">
              <td className="font-mono text-gray-900">{row.item_id}</td>
              <td><VerdictBadge verdict={row.verdict} /></td>
              <td className="text-gray-500">{row.trigger}</td>
              <td className="text-gray-400">{row.started_at ? new Date(row.started_at).toLocaleString() : "—"}</td>
              <td className="text-gray-500">{row.findings.map(f => f.code).join(", ")}</td>
            </tr>)}
        </tbody>
      </table>
    </div>;
}
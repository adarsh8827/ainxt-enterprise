// SPDX-License-Identifier: MIT
// Task F-7: real Verification tab over GET /ecosystem/items/{id}/gate-runs
// (task B-8/B-9's 7 stages) -- replaces the merged FE's 4 static
// always-passing checks (CONFIG_AND_PRODUCTS.md §7 item 13's removal).
//
// Item 6 (2026-09-27): shows every stage for THIS run's actual path (fast
// path: 3 stages; full gate: 6-7, sandbox only if the version has bundled
// files) with live status/duration while a run is still in progress, plus
// an ETA derived from GateRunsResponse.average_stage_durations_ms. Polls
// while the latest run's finished_at is still null -- that's the one
// unambiguous "still actually running" signal (a resolved 'pending'
// verdict, e.g. the compliance-service-disabled case, has finished_at
// set and correctly does NOT keep polling forever).
import { useEffect, useRef, useState } from "react";
import { useEcosystemClient } from "../lib/context/HostContext";
import { VerdictBadge } from "../Badges";
const STAGE_LABELS = {
  manifest: "Manifest",
  license: "License",
  static_safety: "Static safety",
  supply_chain: "Supply chain",
  sandbox: "Sandbox",
  ethics: "Ethics review",
  mcp_connector: "MCP/connector"
};
const FAST_PATH_STAGES = ["manifest", "static_safety"];
const FULL_GATE_STAGES = ["manifest", "license", "static_safety", "supply_chain", "sandbox", "ethics", "mcp_connector"];
const POLL_INTERVAL_MS = 2000;
function stageOrder(run, hasScripts) {
  if (run.is_fast_path) return FAST_PATH_STAGES;
  return hasScripts ? FULL_GATE_STAGES : FULL_GATE_STAGES.filter(s => s !== "sandbox");
}

/** A stage with no timing entry yet is either not-yet-reached ("queued")
 * or was intentionally skipped (cache hit / already-failed short-circuit,
 * gate_service.py's own "skipped" status) -- distinguish using whichever
 * stages DO have a timing entry: once any later stage has run, an earlier
 * stage with no entry must have been skipped, not merely queued. */
function resolveStageStatus(run, order, stage) {
  const timing = run.stage_timings[stage];
  if (timing) return timing;
  if (run.finished_at) return {
    status: "queued",
    duration_ms: null,
    started_at: null
  }; // shouldn't happen once resolved, but never lie as "running"
  const idx = order.indexOf(stage);
  const anyLaterRan = order.slice(idx + 1).some(s => run.stage_timings[s]);
  if (anyLaterRan) return {
    status: "queued",
    duration_ms: null,
    started_at: null
  };
  const anyEarlierRan = order.slice(0, idx).some(s => run.stage_timings[s]);
  const isFirst = idx === 0;
  return {
    status: isFirst || anyEarlierRan ? "running" : "queued",
    duration_ms: null,
    started_at: null
  };
}

// BUG-001 fix: a builtin item (trust_tier="builtin") skips static_safety/
// supply_chain/sandbox/ethics/mcp_connector regardless of trigger
// (gate_service.py's is_builtin branch) -- is_fast_path stays false for
// these runs (they're not the private/self-created synchronous path), so
// they fell into the "Full gate: every stage runs" copy below even though
// the stage list right underneath shows five of seven stages skipped.
// trigger === "admin_provision" is NOT a safe stand-in for this: that same
// trigger is also used for a real full re-gate when a share/scope-widen
// forces one (ensure_full_gate_for_scope_widen in gate_service.py), which
// genuinely runs every stage. The one reliable signal already flowing
// through is each skipped stage's own reason text -- recorded by design
// specifically so the Verification tab can show *why* a stage didn't run.
const BUILTIN_BYPASS_REASON_MARKER = "already reviewed before merge";
function isBuiltinBypass(run) {
  return Object.values(run.stage_timings).some(t => t.status === "skipped" && !!t.reason && t.reason.includes(BUILTIN_BYPASS_REASON_MARKER));
}
function formatMs(ms) {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
function estimateRemainingMs(run, order, averages) {
  if (run.finished_at) return null;
  let remaining = 0;
  let hasAny = false;
  for (const stage of order) {
    if (run.stage_timings[stage]) continue; // already resolved for this run
    const avg = averages[stage];
    if (typeof avg === "number") {
      remaining += avg;
      hasAny = true;
    }
  }
  return hasAny ? remaining : null;
}
export function Verification({
  itemId,
  hasScripts = false
}) {
  const client = useEcosystemClient();
  const [data, setData] = useState(null);
  const pollRef = useRef(null);
  useEffect(() => {
    let cancelled = false;
    const fetchOnce = () => client.getGateRuns(itemId).then(r => {
      if (cancelled) return;
      setData(r);
      const stillRunning = r.gate_runs.length > 0 && !r.gate_runs[0].finished_at;
      if (!stillRunning && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    });
    fetchOnce();
    pollRef.current = setInterval(fetchOnce, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [client, itemId]);
  if (data === null) return <div data-testid="detail-tab-verification-loading">Loading verification history…</div>;
  if (data.gate_runs.length === 0) return <div data-testid="detail-tab-verification-empty">No verification runs yet.</div>;
  const latest = data.gate_runs[0];
  const inProgress = !latest.finished_at;
  const order = stageOrder(latest, hasScripts);
  const remainingMs = inProgress ? estimateRemainingMs(latest, order, data.average_stage_durations_ms) : null;
  const builtinBypass = !latest.is_fast_path && isBuiltinBypass(latest);
  return <div data-testid="detail-tab-verification">
      <div className="flex items-center gap-2 mb-2">
        {inProgress ? <span data-testid="verification-in-progress" className="text-sm text-gray-500">Verifying…</span> : <VerdictBadge verdict={latest.verdict} />}
        <span className="text-xs text-gray-400">scanner {latest.scanner_version}</span>
      </div>

      <p data-testid="verification-path-explanation" className="text-sm text-gray-500 mt-0">
        {latest.is_fast_path ? "Fast path: private, self-created, no bundled scripts — only manifest, secret, and prompt-injection checks run synchronously." : builtinBypass ? "Builtin item: shipped with the platform and already reviewed before merge — ethics, sandbox, supply-chain, and static-safety stages are skipped for this item type." : "Full gate: shared/provisioned, imported, or contains bundled scripts — every stage runs, including sandbox execution and ethics review."}
      </p>

      {inProgress && remainingMs !== null && <p data-testid="verification-eta" className="text-sm text-gray-500">
          Estimated time remaining: ~{formatMs(remainingMs)}
        </p>}

      {inProgress && latest.queue_position !== null && <p data-testid="verification-queue-position" className="text-sm text-gray-500">
          {latest.queue_position === 0 ? "Next up in the verification queue." : `${latest.queue_position} job${latest.queue_position === 1 ? "" : "s"} ahead of this one in the verification queue.`}
        </p>}

      <ul data-testid="verification-stage-list" className="list-none p-0 mb-4">
        {order.map(stage => {
        const timing = resolveStageStatus(latest, order, stage);
        return <li key={stage} data-testid={`verification-stage-${stage}`} data-stage-status={timing.status} className="flex justify-between items-center py-1.5 border-b border-gray-200 text-sm text-gray-900">
              <span>
                {STAGE_LABELS[stage] ?? stage}
                {timing.status === "skipped" && "reason" in timing && timing.reason && <span data-testid={`verification-stage-skip-reason-${stage}`} className="block text-xs text-gray-400">
                    {timing.reason}
                  </span>}
              </span>
              <span className="flex gap-2 items-center text-gray-500">
                <span data-testid={`verification-stage-status-${stage}`}>{timing.status}</span>
                <span className="text-xs text-gray-400">{formatMs(timing.duration_ms)}</span>
              </span>
            </li>;
      })}
      </ul>

      {latest.findings.length === 0 ? <p className="text-gray-500">No findings.</p> : <ul className="list-none p-0">
          {latest.findings.map((f, i) => <li key={i} data-testid="gate-finding" data-severity={f.severity} className={["p-2 mb-2 rounded-md", f.severity === "block" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700"].join(" ")}>
              <strong>{STAGE_LABELS[f.stage] ?? f.stage}</strong> — {f.code}
              <div className="text-sm">{f.message}</div>
            </li>)}
        </ul>}
    </div>;
}
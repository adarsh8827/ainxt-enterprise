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
import type { GateRun, GateRunsResponse, StageTiming } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { VerdictBadge } from "../Badges";

const STAGE_LABELS: Record<string, string> = {
  manifest: "Manifest", license: "License", static_safety: "Static safety",
  supply_chain: "Supply chain", sandbox: "Sandbox", ethics: "Ethics review", mcp_connector: "MCP/connector",
};

const FAST_PATH_STAGES = ["manifest", "static_safety"];
const FULL_GATE_STAGES = ["manifest", "license", "static_safety", "supply_chain", "sandbox", "ethics", "mcp_connector"];

const POLL_INTERVAL_MS = 2000;

function stageOrder(run: GateRun, hasScripts: boolean): string[] {
  if (run.is_fast_path) return FAST_PATH_STAGES;
  return hasScripts ? FULL_GATE_STAGES : FULL_GATE_STAGES.filter((s) => s !== "sandbox");
}

/** A stage with no timing entry yet is either not-yet-reached ("queued")
 * or was intentionally skipped (cache hit / already-failed short-circuit,
 * gate_service.py's own "skipped" status) -- distinguish using whichever
 * stages DO have a timing entry: once any later stage has run, an earlier
 * stage with no entry must have been skipped, not merely queued. */
function resolveStageStatus(run: GateRun, order: string[], stage: string): StageTiming | { status: "queued" | "running"; duration_ms: null; started_at: null } {
  const timing = run.stage_timings[stage];
  if (timing) return timing;
  if (run.finished_at) return { status: "queued", duration_ms: null, started_at: null }; // shouldn't happen once resolved, but never lie as "running"
  const idx = order.indexOf(stage);
  const anyLaterRan = order.slice(idx + 1).some((s) => run.stage_timings[s]);
  if (anyLaterRan) return { status: "queued", duration_ms: null, started_at: null };
  const anyEarlierRan = order.slice(0, idx).some((s) => run.stage_timings[s]);
  const isFirst = idx === 0;
  return { status: isFirst || anyEarlierRan ? "running" : "queued", duration_ms: null, started_at: null };
}

function formatMs(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function estimateRemainingMs(run: GateRun, order: string[], averages: Record<string, number>): number | null {
  if (run.finished_at) return null;
  let remaining = 0;
  let hasAny = false;
  for (const stage of order) {
    if (run.stage_timings[stage]) continue; // already resolved for this run
    const avg = averages[stage];
    if (typeof avg === "number") { remaining += avg; hasAny = true; }
  }
  return hasAny ? remaining : null;
}

export function Verification({ itemId, hasScripts = false }: { itemId: string; hasScripts?: boolean }) {
  const client = useEcosystemClient();
  const [data, setData] = useState<GateRunsResponse | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = () =>
      client.getGateRuns(itemId).then((r) => {
        if (cancelled) return;
        setData(r);
        const stillRunning = r.gate_runs.length > 0 && !r.gate_runs[0]!.finished_at;
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

  const latest = data.gate_runs[0]!;
  const inProgress = !latest.finished_at;
  const order = stageOrder(latest, hasScripts);
  const remainingMs = inProgress ? estimateRemainingMs(latest, order, data.average_stage_durations_ms) : null;

  return (
    <div data-testid="detail-tab-verification">
      <div style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", marginBottom: "var(--eco-space-sm)" }}>
        {inProgress ? (
          <span data-testid="verification-in-progress" style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>Verifying…</span>
        ) : (
          <VerdictBadge verdict={latest.verdict} />
        )}
        <span style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)" }}>scanner {latest.scanner_version}</span>
      </div>

      <p data-testid="verification-path-explanation" style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginTop: 0 }}>
        {latest.is_fast_path
          ? "Fast path: private, self-created, no bundled scripts — only manifest, secret, and prompt-injection checks run synchronously."
          : "Full gate: shared/provisioned, imported, or contains bundled scripts — every stage runs, including sandbox execution and ethics review."}
      </p>

      {inProgress && remainingMs !== null && (
        <p data-testid="verification-eta" style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
          Estimated time remaining: ~{formatMs(remainingMs)}
        </p>
      )}

      {inProgress && latest.queue_position !== null && (
        <p data-testid="verification-queue-position" style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
          {latest.queue_position === 0
            ? "Next up in the verification queue."
            : `${latest.queue_position} job${latest.queue_position === 1 ? "" : "s"} ahead of this one in the verification queue.`}
        </p>
      )}

      <ul data-testid="verification-stage-list" style={{ listStyle: "none", padding: 0, marginBottom: "var(--eco-space-md)" }}>
        {order.map((stage) => {
          const timing = resolveStageStatus(latest, order, stage);
          return (
            <li
              key={stage}
              data-testid={`verification-stage-${stage}`}
              data-stage-status={timing.status}
              style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "6px 0", borderBottom: "1px solid var(--eco-color-border)",
                fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)",
              }}
            >
              <span>
                {STAGE_LABELS[stage] ?? stage}
                {timing.status === "skipped" && "reason" in timing && timing.reason && (
                  <span
                    data-testid={`verification-stage-skip-reason-${stage}`}
                    style={{ display: "block", fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)" }}
                  >
                    {timing.reason}
                  </span>
                )}
              </span>
              <span style={{ display: "flex", gap: "8px", alignItems: "center", color: "var(--eco-color-textSecondary)" }}>
                <span data-testid={`verification-stage-status-${stage}`}>{timing.status}</span>
                <span style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)" }}>{formatMs(timing.duration_ms)}</span>
              </span>
            </li>
          );
        })}
      </ul>

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

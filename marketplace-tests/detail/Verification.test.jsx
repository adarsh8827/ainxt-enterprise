// SPDX-License-Identifier: MIT
// Item 6: the Verification tab must show every stage for the run's ACTUAL
// path (fast path: 3 stages; full gate: 6-7 depending on scripts) with
// live status/duration, an ETA while in progress, and why this run took
// the path it did -- not just the final resolved verdict + findings list
// the old version showed.
import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Verification } from "@marketplace/detail/Verification";
import { HostProvider } from "@marketplace/lib/context/HostContext";
import { LIGHT_TOKENS } from "@marketplace/lib/theme";
function renderWith(response, hasScripts = false) {
  const client = {
    getGateRuns: () => Promise.resolve(response)
  };
  return render(<HostProvider value={{
    client,
    theme: LIGHT_TOKENS,
    layout: "full",
    router: {
      path: "/skills",
      navigate: () => {}
    }
  }}>
      <Verification itemId="item-1" hasScripts={hasScripts} />
    </HostProvider>);
}
const BASE_RUN = {
  id: "run-1",
  version_id: "v1",
  trigger: "ui_add",
  verdict: "pass",
  scanner_version: "2026.09.1",
  started_at: new Date().toISOString(),
  finished_at: new Date().toISOString(),
  findings: [],
  is_fast_path: true,
  queue_position: null,
  stage_timings: {
    manifest: {
      status: "pass",
      duration_ms: 12,
      started_at: new Date().toISOString()
    },
    static_safety: {
      status: "pass",
      duration_ms: 34,
      started_at: new Date().toISOString()
    }
  }
};
describe("Verification", () => {
  it("shows exactly the 3 fast-path stages for a fast-pathed run", async () => {
    renderWith({
      gate_runs: [BASE_RUN],
      average_stage_durations_ms: {}
    });
    await waitFor(() => expect(screen.getByTestId("verification-stage-list")).toBeInTheDocument());
    expect(screen.getByTestId("verification-stage-manifest")).toBeInTheDocument();
    expect(screen.getByTestId("verification-stage-static_safety")).toBeInTheDocument();
    expect(screen.queryByTestId("verification-stage-sandbox")).not.toBeInTheDocument();
    expect(screen.queryByTestId("verification-stage-ethics")).not.toBeInTheDocument();
    expect(screen.getByTestId("verification-path-explanation").textContent).toMatch(/fast path/i);
  });
  it("shows all 7 full-gate stages (including sandbox) when the version has bundled scripts", async () => {
    const fullGateRun = {
      ...BASE_RUN,
      is_fast_path: false,
      stage_timings: {
        manifest: {
          status: "pass",
          duration_ms: 12,
          started_at: null
        },
        license: {
          status: "pass",
          duration_ms: 8,
          started_at: null
        },
        static_safety: {
          status: "pass",
          duration_ms: 34,
          started_at: null
        },
        supply_chain: {
          status: "pass",
          duration_ms: 5,
          started_at: null
        },
        sandbox: {
          status: "pass",
          duration_ms: 2100,
          started_at: null
        },
        ethics: {
          status: "pass",
          duration_ms: 1800,
          started_at: null
        },
        mcp_connector: {
          status: "pass",
          duration_ms: 4,
          started_at: null
        }
      }
    };
    renderWith({
      gate_runs: [fullGateRun],
      average_stage_durations_ms: {}
    }, true);
    await waitFor(() => expect(screen.getByTestId("verification-stage-list")).toBeInTheDocument());
    for (const stage of ["manifest", "license", "static_safety", "supply_chain", "sandbox", "ethics", "mcp_connector"]) {
      expect(screen.getByTestId(`verification-stage-${stage}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("verification-path-explanation").textContent).toMatch(/full gate/i);
  });
  it("omits sandbox for a full-gate item with no bundled scripts", async () => {
    const noScriptsRun = {
      ...BASE_RUN,
      is_fast_path: false
    };
    renderWith({
      gate_runs: [noScriptsRun],
      average_stage_durations_ms: {}
    }, false);
    await waitFor(() => expect(screen.getByTestId("verification-stage-list")).toBeInTheDocument());
    expect(screen.queryByTestId("verification-stage-sandbox")).not.toBeInTheDocument();
  });
  it("shows a live ETA and marks the run in-progress while finished_at is still null", async () => {
    const inProgress = {
      ...BASE_RUN,
      finished_at: null,
      stage_timings: {
        manifest: {
          status: "pass",
          duration_ms: 12,
          started_at: new Date().toISOString()
        }
      }
    };
    renderWith({
      gate_runs: [inProgress],
      average_stage_durations_ms: {
        static_safety: 250
      }
    });
    await waitFor(() => expect(screen.getByTestId("verification-in-progress")).toBeInTheDocument());
    expect(screen.getByTestId("verification-eta").textContent).toMatch(/250ms|0\.3s|estimated/i);
    expect(screen.getByTestId("verification-stage-status-static_safety").textContent).toBe("running");
  });
  it("shows the empty state when no runs exist yet", async () => {
    renderWith({
      gate_runs: [],
      average_stage_durations_ms: {}
    });
    await waitFor(() => expect(screen.getByTestId("detail-tab-verification-empty")).toBeInTheDocument());
  });
  it("shows a skipped stage's real reason (real gap found live, 2026-09-29)", async () => {
    const withSkipReason = {
      ...BASE_RUN,
      is_fast_path: false,
      stage_timings: {
        manifest: {
          status: "pass",
          duration_ms: 12,
          started_at: null
        },
        license: {
          status: "pass",
          duration_ms: 8,
          started_at: null
        },
        static_safety: {
          status: "skipped",
          duration_ms: 0,
          started_at: null,
          reason: "signed catalog hash matched -- fast scan reused"
        },
        supply_chain: {
          status: "skipped",
          duration_ms: 0,
          started_at: null,
          reason: "no scripts or dependencies"
        },
        sandbox: {
          status: "skipped",
          duration_ms: 0,
          started_at: null,
          reason: "no scripts or dependencies"
        },
        ethics: {
          status: "pass",
          duration_ms: 900,
          started_at: null
        },
        mcp_connector: {
          status: "pass",
          duration_ms: 4,
          started_at: null
        }
      }
    };
    renderWith({
      gate_runs: [withSkipReason],
      average_stage_durations_ms: {}
    }, false);
    await waitFor(() => expect(screen.getByTestId("verification-stage-list")).toBeInTheDocument());
    expect(screen.getByTestId("verification-stage-skip-reason-static_safety").textContent).toMatch(/signed catalog hash matched/i);
    expect(screen.getByTestId("verification-stage-skip-reason-supply_chain").textContent).toMatch(/no scripts or dependencies/i);
    // A stage that actually ran must never show a skip-reason element at all.
    expect(screen.queryByTestId("verification-stage-skip-reason-manifest")).not.toBeInTheDocument();
  });
  it("BUG-001: shows builtin-bypass copy, not 'Full gate: every stage runs', when stages were skipped as already-reviewed", async () => {
    const builtinRun = {
      ...BASE_RUN,
      is_fast_path: false,
      stage_timings: {
        manifest: {
          status: "pass",
          duration_ms: 6,
          started_at: null
        },
        license: {
          status: "pass",
          duration_ms: 0,
          started_at: null
        },
        static_safety: {
          status: "skipped",
          duration_ms: 0,
          started_at: null,
          reason: "built-in item shipped with the platform -- already reviewed before merge, not subject to ethics/sandbox/supply-chain/static-safety review"
        },
        supply_chain: {
          status: "skipped",
          duration_ms: 0,
          started_at: null,
          reason: "built-in item shipped with the platform -- already reviewed before merge, not subject to ethics/sandbox/supply-chain/static-safety review"
        },
        sandbox: {
          status: "skipped",
          duration_ms: 0,
          started_at: null,
          reason: "built-in item shipped with the platform -- already reviewed before merge, not subject to ethics/sandbox/supply-chain/static-safety review"
        },
        ethics: {
          status: "skipped",
          duration_ms: 0,
          started_at: null,
          reason: "built-in item shipped with the platform -- already reviewed before merge, not subject to ethics/sandbox/supply-chain/static-safety review"
        },
        mcp_connector: {
          status: "skipped",
          duration_ms: 0,
          started_at: null,
          reason: "built-in item shipped with the platform -- already reviewed before merge, not subject to ethics/sandbox/supply-chain/static-safety review"
        }
      }
    };
    renderWith({
      gate_runs: [builtinRun],
      average_stage_durations_ms: {}
    }, true);
    await waitFor(() => expect(screen.getByTestId("verification-stage-list")).toBeInTheDocument());
    const explanation = screen.getByTestId("verification-path-explanation").textContent ?? "";
    expect(explanation).toMatch(/builtin item/i);
    expect(explanation).not.toMatch(/every stage runs/i);
  });
  it("still shows 'Full gate: every stage runs' for a genuine full-gate run with no builtin-skip stages (e.g. a share/scope-widen re-gate)", async () => {
    const realFullGateRun = {
      ...BASE_RUN,
      is_fast_path: false,
      trigger: "admin_provision",
      stage_timings: {
        manifest: {
          status: "pass",
          duration_ms: 12,
          started_at: null
        },
        license: {
          status: "pass",
          duration_ms: 8,
          started_at: null
        },
        static_safety: {
          status: "pass",
          duration_ms: 34,
          started_at: null
        },
        supply_chain: {
          status: "pass",
          duration_ms: 5,
          started_at: null
        },
        sandbox: {
          status: "pass",
          duration_ms: 2100,
          started_at: null
        },
        ethics: {
          status: "pass",
          duration_ms: 1800,
          started_at: null
        },
        mcp_connector: {
          status: "pass",
          duration_ms: 4,
          started_at: null
        }
      }
    };
    renderWith({
      gate_runs: [realFullGateRun],
      average_stage_durations_ms: {}
    }, true);
    await waitFor(() => expect(screen.getByTestId("verification-stage-list")).toBeInTheDocument());
    expect(screen.getByTestId("verification-path-explanation").textContent).toMatch(/every stage runs/i);
  });
  it("shows the real queue position while a run is genuinely still waiting", async () => {
    const queued = {
      ...BASE_RUN,
      finished_at: null,
      queue_position: 3,
      stage_timings: {}
    };
    renderWith({
      gate_runs: [queued],
      average_stage_durations_ms: {}
    });
    await waitFor(() => expect(screen.getByTestId("verification-queue-position")).toBeInTheDocument());
    expect(screen.getByTestId("verification-queue-position").textContent).toMatch(/3 jobs ahead/i);
  });
  it("says 'next up' when queue_position is exactly 0, never '0 jobs ahead'", async () => {
    const nextUp = {
      ...BASE_RUN,
      finished_at: null,
      queue_position: 0,
      stage_timings: {}
    };
    renderWith({
      gate_runs: [nextUp],
      average_stage_durations_ms: {}
    });
    await waitFor(() => expect(screen.getByTestId("verification-queue-position")).toBeInTheDocument());
    expect(screen.getByTestId("verification-queue-position").textContent).toMatch(/next up/i);
  });
  it("shows no queue-position line at all once queue_position is null (running/resolved)", async () => {
    const running = {
      ...BASE_RUN,
      finished_at: null,
      queue_position: null,
      stage_timings: {}
    };
    renderWith({
      gate_runs: [running],
      average_stage_durations_ms: {}
    });
    await waitFor(() => expect(screen.getByTestId("verification-in-progress")).toBeInTheDocument());
    expect(screen.queryByTestId("verification-queue-position")).not.toBeInTheDocument();
  });
});
// SPDX-License-Identifier: MIT
// Task 3a: admin Sources screen -- catalog status/Sync now, live-search
// toggle, approved websites (read-only), org sources, GitHub credential
// status, ethics/pre-check policies.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AdminSources } from "@marketplace/admin/AdminSources";
import { MOCK_ADMIN_SOURCES } from "@marketplace/lib/client/fixtures";
import { HostProvider } from "@marketplace/lib/context/HostContext";
import { LIGHT_TOKENS } from "@marketplace/lib/theme";

const BASE_POLICY = { who_can_add: "all_users", auto_update_default: false, allowed_licenses_shared: [], live_sources_enabled: false, ethics_review_policy: "always", gate_precheck_enabled: false, gate_precheck_cap_per_hour: 10 };

describe("AdminSources", () => {
  it("shows the catalog URL, last-sync per-shard table, and well-known sites from the mock fixture", async () => {
    renderWithHost(<AdminSources />);
    expect(await screen.findByTestId("admin-sources-catalog-url")).toHaveTextContent(MOCK_ADMIN_SOURCES.catalog_url);
    const rows = await screen.findAllByTestId("admin-sources-shard-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("skill");
    expect(await screen.findByTestId("admin-sources-well-known-row")).toHaveTextContent("docs.example.com");
  });
  it("shows org sources with credential status, never the actual secret", async () => {
    renderWithHost(<AdminSources />);
    const row = await screen.findByTestId("admin-sources-org-source-row");
    expect(row).toHaveTextContent("local");
    expect(row).toHaveTextContent("Not configured");
  });
  it("shows GitHub credential status and its hint when not configured", async () => {
    renderWithHost(<AdminSources />);
    await screen.findByTestId("admin-sources-github-credential");
    expect(screen.getByText(/No GITHUB_IMPORT_TOKEN is configured/)).toBeInTheDocument();
  });
  it("Sync now runs a real sync and the last-sync table reflects the fresh result", async () => {
    renderWithHost(<AdminSources />);
    const rows = await screen.findAllByTestId("admin-sources-shard-row");
    // Fixture's initial state: skill shard shows created=12 from a prior run.
    expect(rows[0]).toHaveTextContent("12");
    fireEvent.click(screen.getByTestId("admin-sources-sync-now"));
    await waitFor(() => expect(screen.getByTestId("admin-sources-sync-now")).not.toBeDisabled());
    // The mock's syncCatalogNow() reports a fresh, no-new-items run (created=0)
    // -- the table must reflect THAT run, not silently keep showing the old one.
    const freshRows = await screen.findAllByTestId("admin-sources-shard-row");
    expect(freshRows[0]).not.toHaveTextContent("12");
  });
  it("toggling live search calls setPolicy with live_sources_enabled", async () => {
    const {
      client
    } = renderWithHost(<AdminSources />);
    const toggle = await screen.findByRole("switch", {
      name: "Live search enabled for this org"
    });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);
    await waitFor(async () => {
      const policy = await client.getPolicy();
      expect(policy.live_sources_enabled).toBe(true);
    });
  });
  it("changing the ethics review policy calls setPolicy with ethics_review_policy", async () => {
    const {
      client
    } = renderWithHost(<AdminSources />);
    await screen.findByTestId("admin-sources-gate-policies");
    fireEvent.click(screen.getByLabelText("Always run ethics review"));
    await waitFor(async () => {
      const policy = await client.getPolicy();
      expect(policy.ethics_review_policy).toBe("always");
    });
  });
  it("the pre-check cap input is disabled until pre-check is enabled", async () => {
    renderWithHost(<AdminSources />);
    await screen.findByTestId("admin-sources-gate-policies");
    expect(screen.getByTestId("admin-sources-precheck-cap")).toBeDisabled();
  });
  it("shows each ecosystem service's commit/started/status from the fixture, with no warnings when all match", async () => {
    renderWithHost(<AdminSources />);
    const rows = await screen.findAllByTestId("admin-sources-service-health-row");
    expect(rows).toHaveLength(3);
    expect(rows.map(r => r.textContent).join("|")).toEqual(expect.stringContaining("gateway"));
    for (const row of rows) {
      expect(row).toHaveTextContent("abc1234");
      expect(row).toHaveTextContent("OK");
    }
    expect(screen.queryByTestId("admin-sources-service-health-warnings")).not.toBeInTheDocument();
  });
  it("warns when a service is missing or its commit doesn't match the gateway's", async () => {
    renderWithHost(<AdminSources />, {
      clientOptions: {
        adminSources: {
          ...MOCK_ADMIN_SOURCES,
          service_health: {
            gateway_commit: "abc1234",
            warnings: ["gate_worker: commit 'def5678' does not match gateway's 'abc1234' -- restart it", "gate_sweeper: never reported a startup (not running, or running code from before this feature)"],
            services: {
              gateway: {
                service: "gateway",
                commit: "abc1234",
                started_at: "2026-09-29T10:00:00Z",
                pid: 1,
                commit_mismatch: false
              },
              gate_worker: {
                service: "gate_worker",
                commit: "def5678",
                started_at: "2026-09-29T10:00:00Z",
                pid: 2,
                commit_mismatch: true
              },
              gate_sweeper: null
            }
          }
        }
      }
    });
    const warnings = await screen.findByTestId("admin-sources-service-health-warnings");
    expect(warnings).toHaveTextContent(/gate_worker.*does not match/);
    expect(warnings).toHaveTextContent(/gate_sweeper.*never reported/);
    const rows = await screen.findAllByTestId("admin-sources-service-health-row");
    expect(rows.find(r => r.textContent?.includes("gate_worker"))).toHaveTextContent("Commit mismatch");
    expect(rows.find(r => r.textContent?.includes("gate_sweeper"))).toHaveTextContent("Never reported");
  });

  // User-flow QA round 8 (2026-10-03, audit finding): savePolicy() had no
  // .catch() at all, same bug as AdminPolicies.jsx's own save() -- a
  // failed save silently reverted with zero indication anything went
  // wrong.
  it("shows a real error, and leaves the toggle unchanged, when a policy save fails", async () => {
    const getAdminSources = vi.fn().mockResolvedValue(MOCK_ADMIN_SOURCES);
    const getPolicy = vi.fn().mockResolvedValue(BASE_POLICY);
    const setPolicy = vi.fn().mockRejectedValue(new Error("Couldn't reach the server."));
    render(
      <HostProvider value={{ client: { getAdminSources, getPolicy, setPolicy }, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <AdminSources />
      </HostProvider>,
    );
    const toggle = await screen.findByRole("switch", { name: "Live search enabled for this org" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);

    expect(await screen.findByTestId("admin-sources-save-error")).toHaveTextContent("Couldn't reach the server.");
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });
});
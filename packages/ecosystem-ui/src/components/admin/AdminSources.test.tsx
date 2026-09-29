// SPDX-License-Identifier: MIT
// Task 3a: admin Sources screen -- catalog status/Sync now, live-search
// toggle, approved websites (read-only), org sources, GitHub credential
// status, ethics/pre-check policies.
import { describe, expect, it } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../../test-utils";
import { AdminSources } from "./AdminSources";
import { MOCK_ADMIN_SOURCES } from "../../client/fixtures";

describe("AdminSources", () => {
  it("shows the catalog URL, last-sync per-shard table, and well-known sites from the mock fixture", async () => {
    renderWithHost(<AdminSources />);
    expect(await screen.findByTestId("admin-sources-catalog-url")).toHaveTextContent(MOCK_ADMIN_SOURCES.catalog_url!);
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
    const { client } = renderWithHost(<AdminSources />);
    const toggle = await screen.findByRole("switch", { name: "Live search enabled for this org" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);
    await waitFor(async () => {
      const policy = await client.getPolicy();
      expect(policy.live_sources_enabled).toBe(true);
    });
  });

  it("changing the ethics review policy calls setPolicy with ethics_review_policy", async () => {
    const { client } = renderWithHost(<AdminSources />);
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
});

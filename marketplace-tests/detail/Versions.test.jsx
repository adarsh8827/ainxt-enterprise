// SPDX-License-Identifier: MIT
// User-flow QA round 8 (2026-10-03, real user question: "rollback option
// what doing just showing version tab?"): this component never had a test
// at all before this round. Rollback was a real, working server call with
// zero UI-visible feedback -- these tests cover the fix: the click now
// routes up through a caller-supplied onRollback (Detail.jsx's own
// confirm-then-run pattern) instead of firing the mutation directly, and
// a `refreshKey` prop forces a refetch once that confirm resolves (itemId
// alone never changes on a rollback, so the original itemId-only effect
// would never have refetched on its own).
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Versions } from "@marketplace/detail/Versions";
import { HostProvider } from "@marketplace/lib/context/HostContext";
import { LIGHT_TOKENS } from "@marketplace/lib/theme";

const VERSIONS = [
  { id: "v2", version: "2.0.0", is_current: true, gate_verdict: "pass", created_at: "2026-10-01T00:00:00Z" },
  { id: "v1", version: "1.0.0", is_current: false, gate_verdict: "pass", created_at: "2026-09-01T00:00:00Z" },
];

function renderVersions(props = {}, getVersions = vi.fn().mockResolvedValue(VERSIONS)) {
  const client = { getVersions };
  return {
    getVersions,
    ...render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <Versions itemId="item-1" installId="install-1" canRollback onRollback={vi.fn()} canUpdate onUpdate={vi.fn()} {...props} />
      </HostProvider>,
    ),
  };
}

describe("Versions", () => {
  it("shows every version with the latest one badged, and a rollback button only on non-latest rows", async () => {
    renderVersions();
    const rows = await screen.findAllByTestId("version-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Latest");
    expect(rows[0].querySelector('[data-testid="rollback-button"]')).toBeNull();
    expect(rows[1]).not.toHaveTextContent("Latest");
    expect(rows[1].querySelector('[data-testid="rollback-button"]')).not.toBeNull();
  });

  // BUG-U05 fix: "latest" and "what this install is actually pinned to"
  // are different facts -- a rollback moves the latter without ever
  // touching the former, so a successful rollback used to have literally
  // no visible effect anywhere in this tab (the user's own live report).
  it("badges the row the install is actually pinned to as 'Currently in use for you', separately from 'Latest', after a real rollback", async () => {
    // Three rows: the install rolled back from the latest (v3) to the
    // middle one (v2) -- leaves a real, still-older row (v1) to roll back
    // to further, which only makes sense if the in-use row (v2) itself
    // correctly stops offering its own (meaningless) rollback button.
    const rolledBack = [
      { id: "v3", version: "3.0.0", is_current: true, is_installed_version: false, gate_verdict: "pass", created_at: "2026-10-03T00:00:00Z" },
      { id: "v2", version: "2.0.0", is_current: false, is_installed_version: true, gate_verdict: "pass", created_at: "2026-10-01T00:00:00Z" },
      { id: "v1", version: "1.0.0", is_current: false, is_installed_version: false, gate_verdict: "pass", created_at: "2026-09-01T00:00:00Z" },
    ];
    renderVersions({}, vi.fn().mockResolvedValue(rolledBack));
    const rows = await screen.findAllByTestId("version-row");
    // The newest row is still "Latest" but is no longer what's in use --
    // it offers Update (move forward), not Rollback (moving "back" to
    // the newest version doesn't make sense).
    expect(rows[0]).toHaveTextContent("Latest");
    expect(rows[0].querySelector('[data-testid="version-in-use-badge"]')).toBeNull();
    expect(rows[0].querySelector('[data-testid="rollback-button"]')).toBeNull();
    expect(rows[0].querySelector('[data-testid="update-button"]')).not.toBeNull();
    // The row the install actually rolled back to shows the in-use badge
    // and offers neither action -- rolling back to (or updating to) the
    // version you're already on is meaningless.
    expect(rows[1]).not.toHaveTextContent("Latest");
    expect(rows[1].querySelector('[data-testid="version-in-use-badge"]')).not.toBeNull();
    expect(rows[1].querySelector('[data-testid="rollback-button"]')).toBeNull();
    expect(rows[1].querySelector('[data-testid="update-button"]')).toBeNull();
    // A genuinely older, not-in-use row still offers a real Rollback.
    expect(rows[2].querySelector('[data-testid="rollback-button"]')).not.toBeNull();
  });

  it("clicking rollback calls the caller's onRollback with that row's version id -- never the client directly", async () => {
    const onRollback = vi.fn();
    renderVersions({ onRollback });
    const button = await screen.findByTestId("rollback-button");
    fireEvent.click(button);
    expect(onRollback).toHaveBeenCalledWith("v1");
  });

  it("has no rollback button at all when canRollback is false, even on a non-current version", async () => {
    renderVersions({ canRollback: false });
    await screen.findAllByTestId("version-row");
    expect(screen.queryByTestId("rollback-button")).not.toBeInTheDocument();
  });

  it("has no rollback or update button when there's no real install (installId null)", async () => {
    renderVersions({ installId: null });
    await screen.findAllByTestId("version-row");
    expect(screen.queryByTestId("rollback-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("update-button")).not.toBeInTheDocument();
  });

  // User-flow QA round 8 (2026-10-03, audit finding): Update was a real,
  // working server call (installs_service.update_to_version) with no
  // button anywhere in the UI that could ever call it.
  it("shows an update button only on the current/newest row, only when canUpdate", async () => {
    renderVersions();
    const rows = await screen.findAllByTestId("version-row");
    expect(rows[0].querySelector('[data-testid="update-button"]')).not.toBeNull();
    expect(rows[1].querySelector('[data-testid="update-button"]')).toBeNull();
  });

  it("has no update button at all when canUpdate is false", async () => {
    renderVersions({ canUpdate: false });
    await screen.findAllByTestId("version-row");
    expect(screen.queryByTestId("update-button")).not.toBeInTheDocument();
  });

  it("clicking update calls the caller's onUpdate with the current row's version id -- never the client directly", async () => {
    const onUpdate = vi.fn();
    renderVersions({ onUpdate });
    const button = await screen.findByTestId("update-button");
    fireEvent.click(button);
    expect(onUpdate).toHaveBeenCalledWith("v2");
  });

  // The real bug: itemId never changes on a rollback, so a fetch effect
  // keyed only on itemId would never re-run once Detail.jsx's confirm-then
  // -run mutation actually resolved -- refreshKey is what forces it to.
  it("refetches versions when refreshKey changes, even though itemId stays the same", async () => {
    const getVersions = vi.fn().mockResolvedValue(VERSIONS);
    const { rerender } = render(
      <HostProvider value={{ client: { getVersions }, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <Versions itemId="item-1" installId="install-1" canRollback onRollback={vi.fn()} refreshKey={0} />
      </HostProvider>,
    );
    await waitFor(() => expect(getVersions).toHaveBeenCalledTimes(1));

    rerender(
      <HostProvider value={{ client: { getVersions }, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <Versions itemId="item-1" installId="install-1" canRollback onRollback={vi.fn()} refreshKey={1} />
      </HostProvider>,
    );
    await waitFor(() => expect(getVersions).toHaveBeenCalledTimes(2));
  });
});

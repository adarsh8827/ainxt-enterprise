// SPDX-License-Identifier: MIT
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { Detail } from "./Detail";
import { HostProvider } from "../context/HostContext";
import { EcosystemConfigProvider } from "../hooks/useEcosystemConfig";
import { MOCK_ITEMS, MOCK_DETAILS, MOCK_CONFIG } from "../client/fixtures";
import { LIGHT_TOKENS } from "../theme";
import type { EcosystemClient } from "../client/EcosystemClient";
import type { ItemDetail } from "../types";

function renderWithClient(client: EcosystemClient, ui: ReactElement, router = { path: "/skills", navigate: () => {} }) {
  return render(
    <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router }}>
      <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>{ui}</EcosystemConfigProvider>
    </HostProvider>,
  );
}

describe("Detail", () => {
  it("has no Copy Link control (removed -- Back + the address bar already cover it)", async () => {
    const item = MOCK_ITEMS[0]!;
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("detail-back")).toBeInTheDocument());
    expect(screen.queryByTestId("detail-copy-link")).not.toBeInTheDocument();
  });

  it("a caller with no scope choice installs on a single click, with no dialog ever appearing", async () => {
    const item = MOCK_ITEMS[0]!;
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: { config: { ...MOCK_CONFIG, caller_permissions: { can_share: false, can_provision: false } } },
    });
    const addButton = await screen.findByTestId("detail-add-button");
    await waitFor(() => expect(addButton).not.toBeDisabled());
    fireEvent.click(addButton);

    // No dialog ever mounts for this caller/item combination -- checked
    // immediately, since a zero-latency mock client resolves install()
    // before a later assertion could tell "never showed" apart from
    // "showed then closed already".
    expect(screen.queryByTestId("add-dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId("detail-add-error")).not.toBeInTheDocument());
  });

  it("a caller with can_share (who_can_share policy allows it) sees the Add dialog -- a real scope choice exists", async () => {
    // Sharing is policy-driven (product correction, 2026-09-27): can_share
    // true means a real scope choice exists (Just me vs. Share with
    // teammates), so the dialog opens rather than installing on one click.
    const item = MOCK_ITEMS[0]!;
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: { config: { ...MOCK_CONFIG, caller_permissions: { can_share: true, can_provision: false } } },
    });
    const addButton = await screen.findByTestId("detail-add-button");
    await waitFor(() => expect(addButton).not.toBeDisabled());
    fireEvent.click(addButton);
    expect(await screen.findByTestId("add-dialog")).toBeInTheDocument();
  });

  it("a caller WITH a real scope choice (marketplace:provision) still sees the Add dialog", async () => {
    const item = MOCK_ITEMS[0]!;
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: { config: { ...MOCK_CONFIG, caller_permissions: { can_share: false, can_provision: true } } },
    });
    const addButton = await screen.findByTestId("detail-add-button");
    await waitFor(() => expect(addButton).not.toBeDisabled());
    fireEvent.click(addButton);
    expect(await screen.findByTestId("add-dialog")).toBeInTheDocument();
  });

  it("a warn-verdict item still shows a confirm before installing, even with no scope choice", async () => {
    const warned: ItemDetail = { ...MOCK_DETAILS["item-exec-assistant"]!, id: "item-warn-for-detail-test", latest_verdict: "warn", allowed_actions: ["install"] };
    renderWithHost(<Detail idOrNamespace={warned.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: { items: [warned], config: { ...MOCK_CONFIG, caller_permissions: { can_share: false, can_provision: false } } },
    });
    const addButton = await screen.findByTestId("detail-add-button");
    await waitFor(() => expect(addButton).not.toBeDisabled());
    fireEvent.click(addButton);
    const dialog = await screen.findByTestId("add-dialog");
    expect(dialog).toHaveTextContent(/warning/i);
    expect(dialog.querySelector('[data-testid="add-dialog-confirm"]')).toHaveTextContent("Continue");
  });

  it("shows the blocked banner for a failed-verdict item and hides the Add button", async () => {
    renderWithHost(<Detail idOrNamespace="item-quick-scraper" typeSlug="skills" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("detail-blocked-banner")).toBeInTheDocument());
    expect(screen.queryByTestId("detail-add-button")).not.toBeInTheDocument();
  });

  it("Back button invokes onBack", async () => {
    const onBack = vi.fn();
    const item = MOCK_ITEMS[0]!;
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={onBack} />);
    await waitFor(() => expect(screen.getByTestId("detail-back")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("detail-back"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  // Item A3 ("Edit skill code is missing") -- an owned item gets an Edit
  // tab and never the "Copy to my skills" button; a read-only item (not
  // owned/administered) gets the reverse. The two are mutually exclusive,
  // driven entirely by allowed_actions' `edit_content` (items_service.py's
  // compute_allowed_actions()), never inferred from trust_tier/publisher.
  // Item 2 (M5 UI-polish round): "Copy to my skills" removed entirely --
  // a read-only item now just shows nothing in the header action slot if
  // it's not installed (no `install` in allowed_actions either, since a
  // built-in/other-owned item was never offered a real Add-for-yourself
  // path -- this package's own compute_allowed_actions() only grants
  // `install` for a genuinely add-able item).
  it("shows the Edit tab for an item allowed_actions marks edit_content, and Installed ▾ once actually installed", async () => {
    const owned: ItemDetail = {
      ...MOCK_DETAILS["item-exec-assistant"]!, id: "item-owned-for-detail-test",
      allowed_actions: ["edit_content", "disable", "uninstall", "report"], install_id: "install-owned-1", enabled: true,
    };
    renderWithHost(<Detail idOrNamespace={owned.id} typeSlug="skills" onBack={() => {}} />, { clientOptions: { items: [owned] } });

    await waitFor(() => expect(screen.getByTestId("detail-tab-trigger-edit")).toBeInTheDocument());
    expect(screen.getByTestId("detail-installed-trigger")).toBeInTheDocument();
    expect(screen.queryByTestId("detail-add-button")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("detail-tab-trigger-edit"));
    expect(await screen.findByTestId("detail-tab-edit-content")).toBeInTheDocument();
  });

  it("a not-yet-installed read-only item has no Edit tab and no header action at all", async () => {
    const item = MOCK_ITEMS[0]!;
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />);

    await waitFor(() => expect(screen.getByTestId("detail-screen")).toBeInTheDocument());
    expect(screen.queryByTestId("detail-tab-trigger-edit")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-installed-trigger")).not.toBeInTheDocument();
    // This fixture has "install" in allowed_actions (not yet installed), so Add shows.
    expect(screen.getByTestId("detail-add-button")).toBeInTheDocument();
  });

  it("hides Add and Installed ▾ for a blocked (failed-verdict) item", async () => {
    renderWithHost(<Detail idOrNamespace="item-quick-scraper" typeSlug="skills" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("detail-blocked-banner")).toBeInTheDocument());
    expect(screen.queryByTestId("detail-add-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-installed-trigger")).not.toBeInTheDocument();
  });

  it("an installed item shows 'Installed ▾' instead of Add, opening a menu with Manage in Yours / Enable-Disable / Versions & rollback / Uninstall", async () => {
    const item = MOCK_ITEMS[0]!;
    const installed: ItemDetail = { ...(MOCK_DETAILS[item.id] ?? MOCK_DETAILS["item-exec-assistant"]!), install_id: "install-1", enabled: true, install_scope: "private", allowed_actions: ["disable", "uninstall", "report"] };
    renderWithHost(<Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />, { clientOptions: { items: [installed] } });

    const trigger = await screen.findByTestId("detail-installed-trigger");
    expect(screen.queryByTestId("detail-add-button")).not.toBeInTheDocument();
    fireEvent.click(trigger);

    const menu = await screen.findByTestId("detail-installed-menu");
    expect(menu).toHaveTextContent("Manage in Yours");
    expect(menu).toHaveTextContent("Disable"); // currently enabled
    expect(menu).toHaveTextContent("Versions & rollback");
    expect(menu).toHaveTextContent("Uninstall");
  });

  it("a required install locks Uninstall with an explanation instead of hiding it silently", async () => {
    const installed: ItemDetail = { ...MOCK_DETAILS["item-exec-assistant"]!, install_id: "install-required-1", enabled: true, install_scope: "required", allowed_actions: ["uninstall", "report"] };
    renderWithHost(<Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />, { clientOptions: { items: [installed] } });

    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    const menu = await screen.findByTestId("detail-installed-menu");
    expect(menu).not.toHaveTextContent(/^Uninstall$/m);
    const lockedItem = screen.getByText("Required");
    expect(lockedItem.closest("button")).toBeDisabled();
    expect(menu).toHaveTextContent(/required by your admin/i);
  });

  it("toggling Enable/Disable from the Installed ▾ menu calls setEnabled for the caller's own install", async () => {
    const installed: ItemDetail = { ...MOCK_DETAILS["item-exec-assistant"]!, install_id: "install-1", enabled: true, install_scope: "private", allowed_actions: ["disable", "uninstall", "report"] };
    const setEnabled = vi.fn().mockResolvedValue(undefined);
    const client = {
      getItem: () => Promise.resolve(installed), getVersions: () => Promise.resolve([]), setEnabled,
    } as unknown as EcosystemClient;
    renderWithClient(client, <Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />);

    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    fireEvent.click(await screen.findByText("Disable"));
    await waitFor(() => expect(setEnabled).toHaveBeenCalledWith("install-1", false));
  });

  it("Versions & rollback switches to the Versions tab", async () => {
    const installed: ItemDetail = { ...MOCK_DETAILS["item-exec-assistant"]!, install_id: "install-1", enabled: true, install_scope: "private", allowed_actions: ["disable", "uninstall", "rollback", "report"] };
    renderWithHost(<Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />, { clientOptions: { items: [installed] } });

    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    fireEvent.click(await screen.findByText("Versions & rollback"));
    await waitFor(() => expect(screen.getByTestId("detail-tab-trigger-versions")).toHaveAttribute("aria-selected", "true"));
  });

  it("Uninstall from the Installed ▾ menu calls uninstall for the caller's own install", async () => {
    const installed: ItemDetail = { ...MOCK_DETAILS["item-exec-assistant"]!, install_id: "install-1", enabled: true, install_scope: "private", allowed_actions: ["disable", "uninstall", "report"] };
    const uninstall = vi.fn().mockResolvedValue(undefined);
    const client = {
      getItem: () => Promise.resolve(installed), getVersions: () => Promise.resolve([]), uninstall,
    } as unknown as EcosystemClient;
    renderWithClient(client, <Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />);

    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    fireEvent.click(await screen.findByText("Uninstall"));
    await waitFor(() => expect(uninstall).toHaveBeenCalledWith("install-1"));
  });
});

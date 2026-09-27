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

  it("a caller with only the now-retired marketplace:share permission installs on a single click too -- share is admin-only now", async () => {
    // Product decision (user-confirmed): every scope beyond private is
    // admin-only (marketplace:provision) now -- can_share alone no
    // longer creates a real scope choice.
    const item = MOCK_ITEMS[0]!;
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: { config: { ...MOCK_CONFIG, caller_permissions: { can_share: true, can_provision: false } } },
    });
    const addButton = await screen.findByTestId("detail-add-button");
    await waitFor(() => expect(addButton).not.toBeDisabled());
    fireEvent.click(addButton);
    expect(screen.queryByTestId("add-dialog")).not.toBeInTheDocument();
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
  it("shows the Edit tab, not Copy to my skills, for an item allowed_actions marks edit_content", async () => {
    const owned: ItemDetail = { ...MOCK_DETAILS["item-exec-assistant"]!, id: "item-owned-for-detail-test", allowed_actions: ["edit_content", "install", "report"] };
    renderWithHost(<Detail idOrNamespace={owned.id} typeSlug="skills" onBack={() => {}} />, { clientOptions: { items: [owned] } });

    await waitFor(() => expect(screen.getByTestId("detail-tab-trigger-edit")).toBeInTheDocument());
    expect(screen.queryByTestId("detail-copy-to-my-skills")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("detail-tab-trigger-edit"));
    expect(await screen.findByTestId("detail-tab-edit-content")).toBeInTheDocument();
  });

  it("shows Copy to my skills, not the Edit tab, for a read-only item", async () => {
    const item = MOCK_ITEMS[0]!;
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />);

    await waitFor(() => expect(screen.getByTestId("detail-copy-to-my-skills")).toBeInTheDocument());
    expect(screen.queryByTestId("detail-tab-trigger-edit")).not.toBeInTheDocument();
  });

  it("hides Copy to my skills for a blocked (failed-verdict) item", async () => {
    renderWithHost(<Detail idOrNamespace="item-quick-scraper" typeSlug="skills" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("detail-blocked-banner")).toBeInTheDocument());
    expect(screen.queryByTestId("detail-copy-to-my-skills")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-tab-trigger-edit")).not.toBeInTheDocument();
  });

  it("Copy to my skills installs on a single click, no form, same name under the caller's own namespace prefix", async () => {
    const item = MOCK_ITEMS[0]!;
    const navigate = vi.fn();
    const createItem = vi.fn().mockResolvedValue({ item_id: "copied-item-1", version_id: "v1", gate_run_id: "gate-1", status: "verifying", provision_scope: "private" });
    const detail = MOCK_DETAILS[item.id] ?? { ...item, install_id: null, enabled: null, publisher: { slug: "acme", type: "org" }, attribution: "", source: { kind: "local", url: null }, manifest: {}, deprecated_at: null, deprecated_by: null };
    const client = { getItem: () => Promise.resolve(detail), getVersions: () => Promise.resolve([]), createItem } as unknown as EcosystemClient;
    renderWithClient(client, <Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />, { path: "/skills", navigate });

    const copyButton = await screen.findByTestId("detail-copy-to-my-skills");
    fireEvent.click(copyButton);

    // No dialog/form ever mounts -- one click is the whole flow.
    expect(screen.queryByTestId("create-form")).not.toBeInTheDocument();
    await waitFor(() => expect(createItem).toHaveBeenCalledTimes(1));

    const [payload] = createItem.mock.calls[0]!;
    const originalName = detail.namespace.split("/")[1];
    expect(payload.namespace).toBe(`${MOCK_CONFIG.caller_default_namespace_prefix}/${originalName}`);
    expect(payload.display_name).toBe(detail.display_name); // same name -- no "(copy)" suffix
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(expect.stringContaining("copied-item-1")));
  });

  it("Copy to my skills shows an inline error, not a dialog, when the caller already has a copy", async () => {
    const item = MOCK_ITEMS[0]!;
    const detail = MOCK_DETAILS[item.id] ?? { ...item, install_id: null, enabled: null, publisher: { slug: "acme", type: "org" }, attribution: "", source: { kind: "local", url: null }, manifest: {}, deprecated_at: null, deprecated_by: null };
    const conflict = Object.assign(new Error("already exists"), { code: "CONFLICT" });
    const client = {
      getItem: () => Promise.resolve(detail),
      getVersions: () => Promise.resolve([]),
      createItem: vi.fn().mockRejectedValue(conflict),
    } as unknown as EcosystemClient;
    renderWithClient(client, <Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />);

    fireEvent.click(await screen.findByTestId("detail-copy-to-my-skills"));
    expect(await screen.findByTestId("detail-copy-error")).toHaveTextContent(/already have a copy/i);
    expect(screen.queryByTestId("copy-to-my-skills-dialog")).not.toBeInTheDocument();
  });

  it("an installed item shows a kebab menu and an enable/disable toggle instead of Add", async () => {
    const item = MOCK_ITEMS[0]!;
    const installed: ItemDetail = { ...(MOCK_DETAILS[item.id] ?? MOCK_DETAILS["item-exec-assistant"]!), install_id: "install-1", enabled: true, allowed_actions: ["disable", "uninstall", "report"] };
    renderWithHost(<Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />, { clientOptions: { items: [installed] } });

    await waitFor(() => expect(screen.getByTestId("toggle-switch")).toBeInTheDocument());
    expect(screen.getByTestId("toggle-switch")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("kebab-trigger")).toBeInTheDocument();
    expect(screen.queryByTestId("detail-add-button")).not.toBeInTheDocument();
  });

  it("toggling the switch off calls setEnabled(false) for the caller's own install", async () => {
    const installed: ItemDetail = { ...MOCK_DETAILS["item-exec-assistant"]!, install_id: "install-1", enabled: true, allowed_actions: ["disable", "uninstall", "report"] };
    const setEnabled = vi.fn().mockResolvedValue(undefined);
    const client = {
      getItem: () => Promise.resolve(installed), getVersions: () => Promise.resolve([]), setEnabled,
    } as unknown as EcosystemClient;
    renderWithClient(client, <Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />);

    fireEvent.click(await screen.findByTestId("toggle-switch"));
    await waitFor(() => expect(setEnabled).toHaveBeenCalledWith("install-1", false));
  });
});

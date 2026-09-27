// SPDX-License-Identifier: MIT
import { describe, expect, it, vi } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { Detail } from "./Detail";
import { MOCK_ITEMS, MOCK_DETAILS, MOCK_CONFIG } from "../client/fixtures";
import type { ItemDetail } from "../types";

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

  it("a caller WITH a real scope choice (marketplace:share/provision) still sees the Add dialog", async () => {
    const item = MOCK_ITEMS[0]!;
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: { config: { ...MOCK_CONFIG, caller_permissions: { can_share: true, can_provision: false } } },
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

  it("Copy to my skills opens a prefilled CreateForm and navigates to the new item on success", async () => {
    const item = MOCK_ITEMS[0]!;
    const navigate = vi.fn();
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />, {
      router: { path: "/skills", navigate },
    });

    await waitFor(() => expect(screen.getByTestId("detail-copy-to-my-skills")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("detail-copy-to-my-skills"));

    const dialog = await screen.findByTestId("copy-to-my-skills-dialog");
    const displayNameInput = dialog.querySelector('[data-testid="create-form-display-name"]') as HTMLInputElement;
    expect(displayNameInput.value).toBe(`${item.display_name} (copy)`);

    fireEvent.change(dialog.querySelector('[data-testid="create-form-namespace"]')!, { target: { value: "me/my-copy" } });
    fireEvent.click(dialog.querySelector('[data-testid="create-form-submit"]')!);

    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("copy-to-my-skills-dialog")).not.toBeInTheDocument();
  });
});

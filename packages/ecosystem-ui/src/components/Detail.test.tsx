// SPDX-License-Identifier: MIT
// Task F-7's own test requirement: "a component test confirming Copy Link
// produces a URL that F-2's nested routing can actually reload to the
// same state" -- verified here as "the path segment matches
// routing.ts's detailPath() shape for this exact item," which is what
// F-2's host router actually reloads against.
import { describe, expect, it, vi } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { Detail } from "./Detail";
import { detailPath } from "../routing";
import { MOCK_ITEMS, MOCK_DETAILS } from "../client/fixtures";
import type { ItemDetail } from "../types";

Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });

describe("Detail", () => {
  it("Copy Link writes a URL whose path matches routing.ts's detailPath() for this item, under the host's own mount point", async () => {
    const item = MOCK_ITEMS[0]!;
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />, {
      router: { path: "/skills", navigate: () => {}, basePath: "/marketplace" },
    });

    await waitFor(() => expect(screen.getByTestId("detail-copy-link")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("detail-copy-link"));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1));
    const written = (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as string;
    const url = new URL(written);
    expect(url.pathname).toBe(`/marketplace${detailPath("skills", item.namespace)}`);
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

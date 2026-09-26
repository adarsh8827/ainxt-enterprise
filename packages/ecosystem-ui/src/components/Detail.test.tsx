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
import { MOCK_ITEMS } from "../client/fixtures";

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
});

// SPDX-License-Identifier: MIT
// Regression test for a real bug found live: a normal (non-admin) user
// saw "Everyone in org" and could successfully install with an
// org/provisioned/required scope, since AddDialog.tsx unconditionally
// rendered all three scope options with no permission check at all.
// Scope visibility must come from config.caller_permissions (CONTRACTS.md
// §8), never inferred client-side from role or hardcoded.
//
// Since the Add-button simplification (M5 UI-parity review, item A4
// follow-up), Detail.tsx no longer even opens this dialog for a caller
// with no scope choice and a clean (non-'warn') item -- it installs
// directly. This dialog is only reached, in that case, when the item
// needs a warning acknowledged, and correspondingly renders NO scope
// fieldset at all (there's nothing to choose) -- these tests render the
// dialog directly (bypassing Detail.tsx's own decision of whether to
// show it), so they still exercise the fieldset's own permission gating
// on its own terms.
import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithHost } from "../../test-utils";
import { AddDialog } from "./AddDialog";
import { MOCK_DETAILS, MOCK_CONFIG } from "../../client/fixtures";

const ITEM = Object.values(MOCK_DETAILS)[0]!;

function renderDialog(callerPermissions: { can_share: boolean; can_provision: boolean }) {
  return renderWithHost(
    <AddDialog item={ITEM} versionId="v1" defaultSurfaces={["chat"]} onClose={() => {}} onInstalled={() => {}} />,
    { clientOptions: { config: { ...MOCK_CONFIG, caller_permissions: callerPermissions } } },
  );
}

describe("AddDialog scope options", () => {
  it("a normal user (no permissions) sees no scope fieldset at all -- there's only ever one option, so nothing to choose", async () => {
    renderDialog({ can_share: false, can_provision: false });
    await screen.findByTestId("add-dialog");
    expect(screen.queryByLabelText("Just me")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/share with teammates/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/everyone in org/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/required/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("add-dialog-confirm")).toHaveTextContent("Continue");
  });

  it("a user with only marketplace:share sees 'Just me' + 'Share with teammates', not the provisioning options", async () => {
    renderDialog({ can_share: true, can_provision: false });
    expect(await screen.findByLabelText("Just me")).toBeInTheDocument();
    expect(screen.getByLabelText(/share with teammates/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/everyone in org/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/required/i)).not.toBeInTheDocument();
  });

  it("an admin (marketplace:provision) sees every scope option, including Required", async () => {
    renderDialog({ can_share: true, can_provision: true });
    expect(await screen.findByLabelText("Just me")).toBeInTheDocument();
    expect(screen.getByLabelText(/share with teammates/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/everyone in org/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/required/i)).toBeInTheDocument();
  });
});

// Task item 2 (M5 UI-parity review): the overlay must be able to scroll a
// dialog taller than the viewport -- a centered flex overlay with no
// overflow clips the top of tall content with no way to reach it. Asserted
// via the overlay's own layout intent (top-aligned + scrollable), since
// vitest/jsdom can't render real viewport clipping.
describe("AddDialog scrolling", () => {
  it("the overlay is top-aligned and scrollable, not center-clipped", async () => {
    renderDialog({ can_share: true, can_provision: true });
    const overlay = await screen.findByTestId("add-dialog");
    expect(overlay).toHaveStyle({ overflowY: "auto", alignItems: "flex-start" });
  });
});

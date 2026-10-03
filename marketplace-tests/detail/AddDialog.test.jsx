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
import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AddDialog } from "@marketplace/detail/AddDialog";
import { MOCK_DETAILS, MOCK_CONFIG } from "@marketplace/lib/client/fixtures";
const ITEM = Object.values(MOCK_DETAILS)[0];
function renderDialog(callerPermissions) {
  return renderWithHost(<AddDialog item={ITEM} versionId="v1" defaultSurfaces={["chat"]} onClose={() => {}} onInstalled={() => {}} />, {
    clientOptions: {
      config: {
        ...MOCK_CONFIG,
        caller_permissions: callerPermissions
      }
    }
  });
}
describe("AddDialog scope options", () => {
  it("a normal user (no permissions) sees no scope fieldset at all -- there's only ever one option, so nothing to choose", async () => {
    renderDialog({
      can_share: false,
      can_provision: false
    });
    await screen.findByTestId("add-dialog");
    expect(screen.queryByLabelText("Just me")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/share with teammates/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/everyone in org/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/required/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("add-dialog-confirm")).toHaveTextContent("Continue");
  });
  it("a user with can_share (who_can_share policy allows it) sees Just me + Share with teammates, but not org-wide options", async () => {
    // Sharing is policy-driven (product correction, 2026-09-27): a normal
    // user's can_share reflects the org's own who_can_share policy, not a
    // fixed RBAC permission -- they get a real scope choice (Just me vs.
    // Share with teammates) but never org-wide provisioning options.
    renderDialog({
      can_share: true,
      can_provision: false
    });
    expect(await screen.findByLabelText("Just me")).toBeInTheDocument();
    expect(screen.getByLabelText(/share with teammates/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/everyone in org/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/required/i)).not.toBeInTheDocument();
  });
  it("an admin (marketplace:provision) sees every scope option, including Required", async () => {
    renderDialog({
      can_share: true,
      can_provision: true
    });
    expect(await screen.findByLabelText("Just me")).toBeInTheDocument();
    expect(screen.getByLabelText(/share with teammates/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/everyone in org/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/required/i)).toBeInTheDocument();
  });
});

// Per-surface toggles round (2026-09-29): the "Surfaces" toggle fieldset
// is gone from this dialog for every caller -- installs always take
// `defaultSurfaces` verbatim now, with no manual per-install override
// exposed here (the admin-only "Advanced" override lives on the Detail
// page instead, reached through a different, admin-gated control).
describe("AddDialog surfaces", () => {
  it("renders no surface-toggle UI, for a normal user or an admin", async () => {
    renderDialog({
      can_share: true,
      can_provision: true
    });
    await screen.findByTestId("add-dialog");
    expect(screen.queryByText("Surfaces")).not.toBeInTheDocument();
    expect(screen.queryByTestId("surface-toggles")).not.toBeInTheDocument();
    expect(screen.queryByTestId("surface-toggle")).not.toBeInTheDocument();
  });
  it("sends defaultSurfaces verbatim to client.install with no user override possible", async () => {
    const {
      fireEvent
    } = await import("@testing-library/react");
    const {
      client
    } = renderWithHost(<AddDialog item={ITEM} versionId="v1" defaultSurfaces={["chat", "agent_studio"]} onClose={() => {}} onInstalled={() => {}} />, {
      clientOptions: {
        config: {
          ...MOCK_CONFIG,
          caller_permissions: {
            can_share: false,
            can_provision: false
          }
        }
      }
    });
    const install = vi.spyOn(client, "install").mockResolvedValue({
      job_id: "job-1",
      status: "queued"
    });
    fireEvent.click(await screen.findByTestId("add-dialog-confirm"));
    expect(install).toHaveBeenCalledWith(ITEM.id, expect.objectContaining({
      surfaces: ["chat", "agent_studio"]
    }), expect.any(String));
  });
});

// Task item 2 (M5 UI-parity review): the overlay must be able to scroll a
// dialog taller than the viewport -- a centered flex overlay with no
// overflow clips the top of tall content with no way to reach it. Asserted
// via the overlay's own layout intent (top-aligned + scrollable), since
// vitest/jsdom can't render real viewport clipping.
describe("AddDialog scrolling", () => {
  it("the overlay is top-aligned and scrollable, not center-clipped", async () => {
    renderDialog({
      can_share: true,
      can_provision: true
    });
    const overlay = await screen.findByTestId("add-dialog");
    expect(overlay.className).toContain("overflow-y-auto");
    expect(overlay.className).toContain("items-start");
  });
});
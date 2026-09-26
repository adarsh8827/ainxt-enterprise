// SPDX-License-Identifier: MIT
// Regression test for a real bug found live: a normal (non-admin) user
// saw "Everyone in org" and could successfully install with an
// org/provisioned/required scope, since AddDialog.tsx unconditionally
// rendered all three scope options with no permission check at all.
// Scope visibility must come from config.caller_permissions (CONTRACTS.md
// §8), never inferred client-side from role or hardcoded.
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
  it("a normal user (no permissions) sees only 'Just me'", async () => {
    renderDialog({ can_share: false, can_provision: false });
    expect(await screen.findByLabelText("Just me")).toBeInTheDocument();
    expect(screen.queryByLabelText(/share with teammates/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/everyone in org/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/required/i)).not.toBeInTheDocument();
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

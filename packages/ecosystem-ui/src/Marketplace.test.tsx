// SPDX-License-Identifier: MIT
// Regression test for a real bug found live: CreateForm.tsx's own
// provisioning picker was gated on config.features.provisioning -- a
// per-*product* flag every caller under that product sees the same
// value for -- not on whether *this caller* actually has
// marketplace:provision. A normal (non-admin) user under the enterprise
// profile (features.provisioning: true for that whole product) saw the
// same org-provisioning picker an admin would.
import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Marketplace } from "./Marketplace";
import { MockEcosystemClient } from "./client/MockEcosystemClient";
import { MOCK_CONFIG } from "./client/fixtures";
import { LIGHT_TOKENS } from "./theme";

function renderCreateFormAt(callerPermissions: { can_share: boolean; can_provision: boolean }) {
  const config = { ...MOCK_CONFIG, caller_permissions: callerPermissions };
  return render(
    <Marketplace
      client={new MockEcosystemClient({ config })}
      layout="full"
      theme={LIGHT_TOKENS}
      config={config}
      router={{ path: "/skills/new", navigate: () => {} }}
    />,
  );
}

describe("Marketplace -> CreateForm provisioning picker", () => {
  it("a normal user (features.provisioning true for the product, but no marketplace:provision) never sees the provisioning picker", async () => {
    renderCreateFormAt({ can_share: false, can_provision: false });
    await waitFor(() => expect(screen.getByTestId("create-form")).toBeInTheDocument());
    expect(screen.queryByTestId("create-form-provision-scope")).not.toBeInTheDocument();
  });

  it("an admin (marketplace:provision) sees the provisioning picker", async () => {
    renderCreateFormAt({ can_share: false, can_provision: true });
    await waitFor(() => expect(screen.getByTestId("create-form")).toBeInTheDocument());
    expect(screen.getByTestId("create-form-provision-scope")).toBeInTheDocument();
  });
});

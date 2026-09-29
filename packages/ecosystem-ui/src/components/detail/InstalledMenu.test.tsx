// SPDX-License-Identifier: MIT
// Plugins phase (docs/ecosystem/PLUGINS_PHASE_PLAN.md §4): a plugin-managed
// install's Uninstall must be locked with an explanation, the same pattern
// `required` already uses -- and must NOT be locked for a normal install,
// so the pre-existing common case doesn't regress.
import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { renderWithHost } from "../../test-utils";
import { InstalledMenu } from "./InstalledMenu";

function baseProps() {
  return {
    enabled: true, required: false,
    onToggleEnabled: vi.fn(), onViewVersions: vi.fn(), onUninstall: vi.fn(),
  };
}

function openMenu() {
  fireEvent.click(screen.getByTestId("detail-installed-trigger"));
}

describe("InstalledMenu -- plugin-managed lock", () => {
  it("offers a real, enabled Uninstall for a normal install (no regression for every existing caller)", () => {
    renderWithHost(<InstalledMenu {...baseProps()} />);
    openMenu();
    expect(screen.getByRole("menuitem", { name: "Uninstall" })).toBeEnabled();
    expect(screen.queryByText(/managed by/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Required")).not.toBeInTheDocument();
  });

  it("locks Uninstall with a generic message when managedByPlugin is true but no name is known", () => {
    renderWithHost(<InstalledMenu {...baseProps()} managedByPlugin />);
    openMenu();
    expect(screen.getByRole("menuitem", { name: /Uninstall/i })).toBeDisabled();
    expect(screen.getByText(/managed by a plugin\. uninstall the plugin instead\./i)).toBeInTheDocument();
  });

  it("locks Uninstall with the plugin's own name when resolvable", () => {
    renderWithHost(<InstalledMenu {...baseProps()} managedByPlugin managedByPluginName="Support Bundle" />);
    openMenu();
    expect(screen.getByText(/managed by the "support bundle" plugin/i)).toBeInTheDocument();
  });

  it("required still wins over managedByPlugin's own message (required is the stricter, admin-set lock)", () => {
    renderWithHost(<InstalledMenu {...baseProps()} required managedByPlugin managedByPluginName="Support Bundle" />);
    openMenu();
    expect(screen.getByText("Required by your admin. It can't be removed.")).toBeInTheDocument();
    expect(screen.queryByText(/managed by/i)).not.toBeInTheDocument();
  });
});

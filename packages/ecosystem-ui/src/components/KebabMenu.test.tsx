// SPDX-License-Identifier: MIT
// Task F-6's own test requirement: "component tests asserting kebab-menu
// contents exactly match the server-provided allowed_actions array for a
// range of fixture items -- never inferring an action's availability from
// any other field client-side."
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { KebabMenu, buildKebabActions, type KebabMenuAction } from "./KebabMenu";
import { HostProvider } from "../context/HostContext";
import type { EcosystemClient } from "../client/EcosystemClient";
import type { AllowedAction } from "../types";

const ALL_HANDLERS: Partial<Record<AllowedAction, () => void>> = {
  enable: vi.fn(), disable: vi.fn(), share: vi.fn(), unshare: vi.fn(),
  update: vi.fn(), rollback: vi.fn(), report: vi.fn(), deprecate: vi.fn(),
  delete_draft: vi.fn(), uninstall: vi.fn(),
};

// KebabMenu's popover now goes through PopoverAnchor, which reads
// useHost().router.path (closes on a route change) -- every render below
// needs a real HostProvider, not a bare component tree.
function renderMenu(actions: KebabMenuAction[]) {
  return render(
    <HostProvider value={{ client: {} as unknown as EcosystemClient, layout: "full", router: { path: "/", navigate: () => {} } }}>
      <KebabMenu actions={actions} />
    </HostProvider>,
  );
}

describe("KebabMenu / buildKebabActions", () => {
  it("renders exactly the actions present in allowed_actions, nothing more", () => {
    const allowed: AllowedAction[] = ["uninstall", "disable", "report"];
    const actions = buildKebabActions(allowed, ALL_HANDLERS);
    renderMenu(actions);
    fireEvent.click(screen.getByTestId("kebab-trigger"));
    const items = screen.getAllByTestId("kebab-menu-item").map((el) => el.textContent);
    expect(items).toEqual(["Disable", "Report", "Uninstall"]);
  });

  it("renders zero action items when allowed_actions is empty, even if every handler exists", () => {
    const actions = buildKebabActions([], ALL_HANDLERS);
    renderMenu(actions);
    fireEvent.click(screen.getByTestId("kebab-trigger"));
    expect(screen.queryAllByTestId("kebab-menu-item")).toHaveLength(0);
  });

  it("never infers an action from another field -- a forged allowed_actions array is trusted verbatim (server is the real enforcement)", () => {
    // This is exactly the scenario the backend's own test guards against
    // (installs_service tests: "forges a client-side allowed_actions array
    // and confirms the server independently re-checks and rejects") --
    // here we confirm the CLIENT side of that contract: this component
    // renders purely from the array, it does not second-guess it.
    const allowed: AllowedAction[] = ["delete_draft"];
    const actions = buildKebabActions(allowed, ALL_HANDLERS);
    renderMenu(actions);
    fireEvent.click(screen.getByTestId("kebab-trigger"));
    expect(screen.getAllByTestId("kebab-menu-item").map((el) => el.textContent)).toEqual(["Delete draft"]);
  });

  it("omits an action present in allowed_actions if the caller supplied no handler for it", () => {
    const allowed: AllowedAction[] = ["force_disable", "report"];
    const actions = buildKebabActions(allowed, { report: vi.fn() });
    expect(actions.map((a) => a.action)).toEqual(["report"]);
  });

  it("calls the matching handler and closes the menu on selection", () => {
    const onSelect = vi.fn();
    const actions = buildKebabActions(["report"], { report: onSelect });
    renderMenu(actions);
    fireEvent.click(screen.getByTestId("kebab-trigger"));
    fireEvent.click(screen.getByTestId("kebab-menu-item"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("kebab-menu")).not.toBeInTheDocument();
  });
});

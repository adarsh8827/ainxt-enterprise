// SPDX-License-Identifier: MIT
// Task item 5 (M5 UI-parity review): the "+ Add" menu must contain every
// option from the reference mock, in order, with Coming-soon entries
// always visible-but-disabled (never omitted, CONTRACTS.md §8) and admin
// entries hidden outright (not just disabled) for a normal user.
import { describe, expect, it, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AddMenu } from "./AddMenu";
import { MOCK_CONFIG } from "../client/fixtures";

function openMenu() {
  fireEvent.click(screen.getByTestId("add-menu-trigger"));
}

describe("AddMenu", () => {
  it("a normal user sees Create with AI + skill actions, all 3 coming-soon types, and no admin section", () => {
    const config = { ...MOCK_CONFIG, caller_permissions: { can_share: false, can_provision: false } };
    renderWithHost(<AddMenu activeSlug="skills" onSelect={() => {}} onCreateWithAi={() => {}} />, { clientOptions: { config } });
    openMenu();

    expect(screen.getByTestId("add-menu-create-with-ai")).toBeInTheDocument();
    expect(screen.getByTestId("add-menu-new")).toBeInTheDocument();
    expect(screen.getByTestId("add-menu-upload")).toBeInTheDocument();
    expect(screen.getByTestId("add-menu-import")).toBeInTheDocument();

    expect(screen.getByTestId("add-menu-mcp_server-coming-soon")).toBeDisabled();
    expect(screen.getByTestId("add-menu-connector-coming-soon")).toBeDisabled();
    expect(screen.getByTestId("add-menu-plugin-coming-soon")).toBeDisabled();

    expect(screen.queryByTestId("add-menu-add-source")).not.toBeInTheDocument();
    expect(screen.queryByTestId("add-menu-provision-for-org")).not.toBeInTheDocument();
    expect(screen.queryByText("Admin")).not.toBeInTheDocument();
  });

  it("an admin (marketplace:provision) additionally sees the Admin section", () => {
    const config = { ...MOCK_CONFIG, caller_permissions: { can_share: true, can_provision: true } };
    renderWithHost(<AddMenu activeSlug="skills" onSelect={() => {}} />, { clientOptions: { config } });
    openMenu();

    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByTestId("add-menu-add-source")).toBeDisabled();
    expect(screen.getByTestId("add-menu-provision-for-org")).not.toBeDisabled();
  });

  it("without an onCreateWithAi callback, the entry is omitted entirely -- never a dead button", () => {
    renderWithHost(<AddMenu activeSlug="skills" onSelect={() => {}} />, { clientOptions: { config: MOCK_CONFIG } });
    openMenu();
    expect(screen.queryByTestId("add-menu-create-with-ai")).not.toBeInTheDocument();
  });

  it("Create with AI invokes the callback and closes the menu", () => {
    const onCreateWithAi = vi.fn();
    renderWithHost(<AddMenu activeSlug="skills" onSelect={() => {}} onCreateWithAi={onCreateWithAi} />, { clientOptions: { config: MOCK_CONFIG } });
    openMenu();
    fireEvent.click(screen.getByTestId("add-menu-create-with-ai"));
    expect(onCreateWithAi).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("add-menu")).not.toBeInTheDocument();
  });

  it("coming-soon entries never invoke onSelect even if somehow clicked", () => {
    const onSelect = vi.fn();
    renderWithHost(<AddMenu activeSlug="skills" onSelect={onSelect} />, { clientOptions: { config: MOCK_CONFIG } });
    openMenu();
    fireEvent.click(screen.getByTestId("add-menu-mcp_server-coming-soon"));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("Provision for org navigates to the admin provisioning screen", () => {
    const navigate = vi.fn();
    const config = { ...MOCK_CONFIG, caller_permissions: { can_share: true, can_provision: true } };
    renderWithHost(<AddMenu activeSlug="skills" onSelect={() => {}} />, {
      clientOptions: { config },
      router: { path: "/skills", navigate },
    });
    openMenu();
    fireEvent.click(screen.getByTestId("add-menu-provision-for-org"));
    expect(navigate).toHaveBeenCalledWith("/admin/provisioning");
  });

  it("for a not-yet-available type (e.g. plugin), skill actions and Create with AI are absent -- only the coming-soon list shows", () => {
    renderWithHost(<AddMenu activeSlug="plugins" onSelect={() => {}} onCreateWithAi={() => {}} />, { clientOptions: { config: MOCK_CONFIG } });
    openMenu();
    expect(screen.queryByTestId("add-menu-create-with-ai")).not.toBeInTheDocument();
    expect(screen.queryByTestId("add-menu-new")).not.toBeInTheDocument();
    expect(screen.getByTestId("add-menu-plugin-coming-soon")).toBeInTheDocument();
  });
});

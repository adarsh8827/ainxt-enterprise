// SPDX-License-Identifier: MIT
// User-flow QA round 8 (2026-10-03, audit finding): "Make required" fired
// immediately with zero confirmation -- locks the item org-wide so no
// user may disable it. This file never existed before this round.
import { describe, expect, it } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { AdminProvisioning } from "@marketplace/admin/AdminProvisioning";

describe("AdminProvisioning", () => {
  it("Make required confirms before firing, and only runs once confirmed", async () => {
    renderWithHost(<AdminProvisioning />);
    fireEvent.change(screen.getByTestId("admin-provisioning-item-id"), { target: { value: "item-123" } });
    fireEvent.click(screen.getByTestId("admin-provisioning-require"));

    expect(await screen.findByTestId("confirm-dialog")).toBeInTheDocument();
    expect(screen.queryByTestId("admin-provisioning-result")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(screen.getByTestId("admin-provisioning-result")).toHaveTextContent(/required/i));
  });

  it("cancelling the confirmation never calls require", async () => {
    renderWithHost(<AdminProvisioning />);
    fireEvent.change(screen.getByTestId("admin-provisioning-item-id"), { target: { value: "item-123" } });
    fireEvent.click(screen.getByTestId("admin-provisioning-require"));
    fireEvent.click(await screen.findByTestId("confirm-dialog-cancel"));
    expect(screen.queryByTestId("admin-provisioning-result")).not.toBeInTheDocument();
  });

  it("Make optional (the safe, reversible direction) stays immediate -- no confirmation shown", async () => {
    renderWithHost(<AdminProvisioning />);
    fireEvent.change(screen.getByTestId("admin-provisioning-item-id"), { target: { value: "item-123" } });
    fireEvent.click(screen.getByTestId("admin-provisioning-unrequire"));
    expect(screen.queryByTestId("confirm-dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("admin-provisioning-result")).toHaveTextContent(/org provisioned/i));
  });
});

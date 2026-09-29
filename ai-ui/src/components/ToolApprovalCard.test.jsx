// SPDX-License-Identifier: MIT
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import ToolApprovalCard from "./ToolApprovalCard.jsx";

afterEach(() => cleanup());

describe("ToolApprovalCard", () => {
  it("renders tool name, classification, target, and params", () => {
    render(
      <ToolApprovalCard
        toolName="update_issue"
        classification="write"
        target="acme/jira"
        params={{ issue_id: "PROJ-123", status: "Done" }}
        onApprove={() => {}}
        onDeny={() => {}}
      />,
    );
    expect(screen.getByText("update_issue")).toBeInTheDocument();
    expect(screen.getByTestId("tool-approval-classification")).toHaveTextContent("write");
    expect(screen.getByText("on acme/jira")).toBeInTheDocument();
    expect(screen.getByText("PROJ-123")).toBeInTheDocument();
  });

  it("calls onApprove when Approve is clicked", () => {
    const onApprove = vi.fn();
    render(<ToolApprovalCard toolName="t" classification="write" onApprove={onApprove} onDeny={() => {}} />);
    fireEvent.click(screen.getByTestId("tool-approval-approve"));
    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  it("calls onDeny when Deny is clicked, not onApprove", () => {
    const onApprove = vi.fn();
    const onDeny = vi.fn();
    render(<ToolApprovalCard toolName="t" classification="destructive" onApprove={onApprove} onDeny={onDeny} />);
    fireEvent.click(screen.getByTestId("tool-approval-deny"));
    expect(onDeny).toHaveBeenCalledTimes(1);
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("disables both buttons while busy", () => {
    render(<ToolApprovalCard toolName="t" classification="write" busy onApprove={() => {}} onDeny={() => {}} />);
    expect(screen.getByTestId("tool-approval-approve")).toBeDisabled();
    expect(screen.getByTestId("tool-approval-deny")).toBeDisabled();
  });
});

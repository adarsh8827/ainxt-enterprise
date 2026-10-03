// SPDX-License-Identifier: MIT
// User-flow QA round 8 (2026-10-03): see Yours.jsx's own comment on the
// "report" kebab action for the real bug this replaces (immediate fire,
// hardcoded reason, no error handling).
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReportDialog } from "@marketplace/ReportDialog";

describe("ReportDialog", () => {
  it("Submit is disabled until a reason is typed, and disabled again for a whitespace-only reason", () => {
    render(<ReportDialog open itemName="French Sentence Translator" onSubmit={vi.fn()} onCancel={vi.fn()} />);
    const submit = screen.getByTestId("report-dialog-submit");
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByTestId("report-dialog-reason"), { target: { value: "   " } });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByTestId("report-dialog-reason"), { target: { value: "  a real reason  " } });
    expect(submit).not.toBeDisabled();
  });

  it("calls onSubmit with the trimmed reason and shows success once it resolves", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ReportDialog open itemName="Test Skill" onSubmit={onSubmit} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByTestId("report-dialog-reason"), { target: { value: "  misleading description  " } });
    fireEvent.click(screen.getByTestId("report-dialog-submit"));
    expect(onSubmit).toHaveBeenCalledWith("misleading description");
    expect(await screen.findByTestId("report-dialog-success")).toBeInTheDocument();
  });

  it("shows a real error and does not show success when the backend rejects it", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("Couldn't reach the server."));
    render(<ReportDialog open itemName="Test Skill" onSubmit={onSubmit} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByTestId("report-dialog-reason"), { target: { value: "something is wrong" } });
    fireEvent.click(screen.getByTestId("report-dialog-submit"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't reach the server.");
    expect(screen.queryByTestId("report-dialog-success")).not.toBeInTheDocument();
  });

  it("resets its own state (reason, error, success) every time it's reopened", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<ReportDialog open itemName="Test Skill" onSubmit={onSubmit} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByTestId("report-dialog-reason"), { target: { value: "first report" } });
    fireEvent.click(screen.getByTestId("report-dialog-submit"));
    await waitFor(() => expect(screen.getByTestId("report-dialog-success")).toBeInTheDocument());

    rerender(<ReportDialog open={false} itemName="Test Skill" onSubmit={onSubmit} onCancel={vi.fn()} />);
    rerender(<ReportDialog open itemName="Test Skill" onSubmit={onSubmit} onCancel={vi.fn()} />);

    expect(screen.queryByTestId("report-dialog-success")).not.toBeInTheDocument();
    expect(screen.getByTestId("report-dialog-reason")).toHaveValue("");
    expect(screen.getByTestId("report-dialog-submit")).toBeDisabled();
  });

  it("renders nothing at all when closed", () => {
    render(<ReportDialog open={false} itemName="Test Skill" onSubmit={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.queryByTestId("report-dialog")).not.toBeInTheDocument();
  });
});

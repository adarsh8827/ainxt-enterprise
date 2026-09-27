// SPDX-License-Identifier: MIT
// Task F-9's own test requirement: "a component test reproducing the
// mock's quick-scraper scenario exactly (a GPL-licensed upload shows a
// blocked state with the specific reason, not a generic error)."
import { describe, expect, it, vi } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../../test-utils";
import { UploadFlow } from "./UploadFlow";
import { EcosystemApiError } from "../../client/EcosystemClient";
import { MockEcosystemClient } from "../../client/MockEcosystemClient";

describe("UploadFlow", () => {
  it("shows the specific LICENSE_NOT_ALLOWED reason, not a generic error, for a GPL-licensed bundle (quick-scraper scenario)", async () => {
    vi.spyOn(MockEcosystemClient.prototype, "uploadItem").mockRejectedValueOnce(
      new EcosystemApiError("LICENSE_NOT_ALLOWED", "GPL-3.0-only is not MIT/Apache-2.0-compatible.", false),
    );

    const { container } = renderWithHost(<UploadFlow itemType="skill" onUploaded={() => {}} onCancel={() => {}} />);

    const file = new File(["fake zip bytes"], "quick-scraper.skill", { type: "application/zip" });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.change(screen.getByTestId("upload-namespace"), { target: { value: "acme/quick-scraper" } });

    fireEvent.click(screen.getByTestId("upload-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("upload-blocked-banner")).toBeInTheDocument();
    });
    expect(screen.getByTestId("upload-blocked-banner")).toHaveTextContent(/MIT\/Apache-2\.0/);
    expect(screen.queryByRole("alert")).not.toHaveTextContent(/Couldn't upload this bundle/);
  });

  it("shows an acknowledgement checkbox (not a dead-end block) for a disallowed license, and resubmits with it once checked", async () => {
    const uploadSpy = vi.spyOn(MockEcosystemClient.prototype, "uploadItem");
    uploadSpy.mockRejectedValueOnce(
      new EcosystemApiError("LICENSE_ACKNOWLEDGEMENT_REQUIRED", "not MIT/Apache-2.0.", false, { reason: "acknowledgement_required" }),
    );
    uploadSpy.mockResolvedValueOnce({ item_id: "item-1", version_id: "v1", gate_run_id: "g1", status: "verifying", provision_scope: "private" });

    const onUploaded = vi.fn();
    const { container } = renderWithHost(<UploadFlow itemType="skill" onUploaded={onUploaded} onCancel={() => {}} />);

    const file = new File(["fake zip bytes"], "gpl-skill.skill", { type: "application/zip" });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.change(screen.getByTestId("upload-namespace"), { target: { value: "acme/gpl-skill" } });
    fireEvent.click(screen.getByTestId("upload-submit"));

    await waitFor(() => expect(screen.getByTestId("upload-ack-prompt")).toBeInTheDocument());
    expect(screen.queryByTestId("upload-blocked-banner")).not.toBeInTheDocument();
    expect(screen.getByTestId("upload-submit")).toBeDisabled();

    fireEvent.click(screen.getByTestId("upload-license-acknowledge"));
    expect(screen.getByTestId("upload-submit")).not.toBeDisabled();
    fireEvent.click(screen.getByTestId("upload-submit"));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith("item-1"));
    const secondCallForm = (uploadSpy.mock.calls as unknown as FormData[][])[1]![0]!;
    expect(secondCallForm.get("license_acknowledged")).toBe("true");
  });

  it("shows a self-authored checkbox for a missing license, defaulting it to MIT once checked", async () => {
    const uploadSpy = vi.spyOn(MockEcosystemClient.prototype, "uploadItem");
    uploadSpy.mockRejectedValueOnce(
      new EcosystemApiError("LICENSE_ACKNOWLEDGEMENT_REQUIRED", "license required.", false, { reason: "missing_license" }),
    );
    uploadSpy.mockResolvedValueOnce({ item_id: "item-2", version_id: "v1", gate_run_id: "g1", status: "verifying", provision_scope: "private" });

    const { container } = renderWithHost(<UploadFlow itemType="skill" onUploaded={() => {}} onCancel={() => {}} />);
    const file = new File(["fake zip bytes"], "no-license.skill", { type: "application/zip" });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.change(screen.getByTestId("upload-namespace"), { target: { value: "acme/no-license" } });
    fireEvent.click(screen.getByTestId("upload-submit"));

    await waitFor(() => expect(screen.getByTestId("upload-self-authored")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("upload-self-authored"));
    fireEvent.click(screen.getByTestId("upload-submit"));

    await waitFor(() => expect(uploadSpy).toHaveBeenCalledTimes(2));
    const secondCallForm = (uploadSpy.mock.calls as unknown as FormData[][])[1]![0]!;
    expect(secondCallForm.get("self_authored")).toBe("true");
  });

  it("rejects a non-.zip/.skill file client-side before ever calling the backend", () => {
    const uploadSpy = vi.spyOn(MockEcosystemClient.prototype, "uploadItem");
    const { container } = renderWithHost(<UploadFlow itemType="skill" onUploaded={() => {}} onCancel={() => {}} />);

    const file = new File(["not a bundle"], "notes.txt", { type: "text/plain" });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    expect(screen.getByText(/Only \.zip or \.skill bundles/)).toBeInTheDocument();
    expect(uploadSpy).not.toHaveBeenCalled();
  });
});

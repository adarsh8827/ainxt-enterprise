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

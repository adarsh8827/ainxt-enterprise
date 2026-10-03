// SPDX-License-Identifier: MIT
// Tiered license policy (ECOSYSTEM_PLAN.md §11.2, task C): "Just me"
// (private) may declare a non-MIT/Apache license via an explicit
// acknowledgement, or leave it blank if self-authored (defaults to MIT).
// Any other scope stays on the strict MIT/Apache-2.0-only dropdown.
import { describe, expect, it, vi } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "../test-utils";
import { CreateForm } from "@marketplace/create/CreateForm";
import { MockEcosystemClient } from "@marketplace/lib/client/MockEcosystemClient";
function fillRequiredFields() {
  fireEvent.change(screen.getByTestId("create-form-namespace"), {
    target: {
      value: "acme/my-skill"
    }
  });
  fireEvent.change(screen.getByTestId("create-form-display-name"), {
    target: {
      value: "My Skill"
    }
  });
  fireEvent.change(screen.getByTestId("create-form-description"), {
    target: {
      value: "does a thing"
    }
  });
  fireEvent.change(screen.getByPlaceholderText("What should the model do when this skill is invoked?"), {
    target: {
      value: "do the thing"
    }
  });
}
describe("CreateForm -- tiered license policy", () => {
  it("submits normally with the default MIT license, no acknowledgement UI shown", async () => {
    const createSpy = vi.spyOn(MockEcosystemClient.prototype, "createItem");
    renderWithHost(<CreateForm itemType="skill" onCreated={() => {}} onCancel={() => {}} canProvision={false} />);
    fillRequiredFields();
    expect(screen.queryByTestId("create-form-license-ack-prompt")).not.toBeInTheDocument();
    expect(screen.getByTestId("create-form-submit")).not.toBeDisabled();
    fireEvent.click(screen.getByTestId("create-form-submit"));
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    const payload = createSpy.mock.calls[0][0];
    expect(payload.license).toBe("MIT");
    expect(payload.license_acknowledged).toBeUndefined();
  });
  it("requires acknowledgement for a custom, disallowed license in the private (\"Just me\") scope", async () => {
    const createSpy = vi.spyOn(MockEcosystemClient.prototype, "createItem");
    renderWithHost(<CreateForm itemType="skill" onCreated={() => {}} onCancel={() => {}} canProvision={false} />);
    fillRequiredFields();
    fireEvent.click(screen.getByTestId("create-form-license-toggle-custom"));
    fireEvent.change(screen.getByTestId("create-form-license-custom"), {
      target: {
        value: "GPL-3.0-only"
      }
    });
    expect(screen.getByTestId("create-form-license-ack-prompt")).toBeInTheDocument();
    expect(screen.getByTestId("create-form-submit")).toBeDisabled();
    fireEvent.click(screen.getByTestId("create-form-license-acknowledge"));
    expect(screen.getByTestId("create-form-submit")).not.toBeDisabled();
    fireEvent.click(screen.getByTestId("create-form-submit"));
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    const payload = createSpy.mock.calls[0][0];
    expect(payload.license).toBe("GPL-3.0-only");
    expect(payload.license_acknowledged).toBe(true);
  });
  it("offers a self-authored default-to-MIT option for a blank custom license", async () => {
    const createSpy = vi.spyOn(MockEcosystemClient.prototype, "createItem");
    renderWithHost(<CreateForm itemType="skill" onCreated={() => {}} onCancel={() => {}} canProvision={false} />);
    fillRequiredFields();
    fireEvent.click(screen.getByTestId("create-form-license-toggle-custom"));
    fireEvent.change(screen.getByTestId("create-form-license-custom"), {
      target: {
        value: ""
      }
    });
    expect(screen.getByTestId("create-form-license-self-authored-prompt")).toBeInTheDocument();
    expect(screen.getByTestId("create-form-submit")).toBeDisabled();
    fireEvent.click(screen.getByTestId("create-form-license-self-authored"));
    fireEvent.click(screen.getByTestId("create-form-submit"));
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    const payload = createSpy.mock.calls[0][0];
    expect(payload.self_authored).toBe(true);
  });
  it("has no custom-license escape hatch for a non-private scope -- stays strict MIT/Apache-2.0", async () => {
    renderWithHost(<CreateForm itemType="skill" onCreated={() => {}} onCancel={() => {}} canProvision={true} />);
    fillRequiredFields();
    fireEvent.change(screen.getByTestId("create-form-provision-scope"), {
      target: {
        value: "org_default_on"
      }
    });
    expect(screen.queryByTestId("create-form-license-toggle-custom")).not.toBeInTheDocument();
    expect(screen.getByTestId("create-form-license")).toBeInTheDocument();
  });
});
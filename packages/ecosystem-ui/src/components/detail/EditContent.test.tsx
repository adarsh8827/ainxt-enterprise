// SPDX-License-Identifier: MIT
// Item A3 ("Edit skill code is missing"): file-tree + editor Save flow.
// CodeMirror itself is exercised via plain rendering only (its internal
// editing surface isn't a normal <textarea>, so simulating keystrokes into
// it here would be brittle jsdom-only theater -- Save's actual wiring is
// verified against the file's already-loaded content plus the plain
// <input> controls this component owns directly: license, add/rename/
// delete file).
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { EditContent } from "./EditContent";
import { HostProvider } from "../../context/HostContext";
import { EcosystemConfigProvider } from "../../hooks/useEcosystemConfig";
import { MOCK_CONFIG } from "../../client/fixtures";
import { LIGHT_TOKENS } from "../../theme";
import type { EcosystemClient } from "../../client/EcosystemClient";
import type { ItemDetail, NewVersionResult } from "../../types";

function makeItem(overrides: Partial<ItemDetail> = {}): ItemDetail {
  return {
    id: "item-owned-1", namespace: "acme/owned-skill", item_type: "skill",
    display_name: "Owned Skill", description: "A skill the caller owns.", category: "productivity",
    tags: [], icon_url: null, trust_tier: "community", license: "MIT", status: "active",
    is_featured: false, is_new: false, latest_version: "1.0.0", latest_verdict: "pass",
    allowed_actions: ["edit_content", "install", "report"],
    install_id: null, enabled: null, install_scope: null, install_surfaces: null, has_other_installs: false, compatibility: "chat",
    publisher: { slug: "acme", type: "user" }, attribution: "MIT License",
    source: { kind: "local", url: null },
    manifest: { instructions: "Do the thing.", files: { "references/notes.md": "some notes" } },
    deprecated_at: null, deprecated_by: null,
    ...overrides,
  };
}

function renderEditContent(item: ItemDetail, createNewVersion: EcosystemClient["createNewVersion"], onSaved = vi.fn()) {
  const client = { createNewVersion } as unknown as EcosystemClient;
  return {
    onSaved,
    ...render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <EditContent item={item} onSaved={onSaved} />
        </EcosystemConfigProvider>
      </HostProvider>,
    ),
  };
}

describe("EditContent", () => {
  it("shows SKILL.md plus every bundled file in the file tree", () => {
    renderEditContent(makeItem(), vi.fn());
    expect(screen.getByTestId("edit-content-file-SKILL.md")).toBeInTheDocument();
    expect(screen.getByTestId("edit-content-file-references/notes.md")).toBeInTheDocument();
  });

  it("Save sends the loaded content and license unchanged when nothing was edited", async () => {
    const createNewVersion = vi.fn().mockResolvedValue({ item_id: "item-owned-1", version_id: "v2", gate_run_id: "gate-2", status: "verifying" } satisfies NewVersionResult);
    const { onSaved } = renderEditContent(makeItem(), createNewVersion);

    fireEvent.click(screen.getByTestId("edit-content-save"));

    await waitFor(() => expect(createNewVersion).toHaveBeenCalledTimes(1));
    expect(createNewVersion).toHaveBeenCalledWith(
      "item-owned-1",
      { instructions: "Do the thing.", files: [{ name: "references/notes.md", content: "some notes" }] },
      "MIT",
      { licenseAcknowledged: false },
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId("edit-content-saved-banner")).toBeInTheDocument();
  });

  // Task C (ECOSYSTEM_PLAN.md §11.2): a disallowed license no longer
  // disables Save client-side outright -- whether it's fine depends on
  // this item's current install footprint (Tier 2 vs Tier 3), which this
  // editor doesn't know; it reacts to the server's real response instead.
  it("Save is not disabled just for typing a disallowed license -- it tries the server first", () => {
    renderEditContent(makeItem(), vi.fn());
    fireEvent.change(screen.getByTestId("edit-content-license"), { target: { value: "GPL-3.0-only" } });
    expect(screen.getByTestId("edit-content-save")).not.toBeDisabled();
    expect(screen.queryByTestId("edit-content-license-ack-prompt")).not.toBeInTheDocument();
  });

  it("shows an acknowledgement checkbox once the server says it's required, and resubmits with it once checked", async () => {
    const apiError = Object.assign(new Error("not allowed"), {
      code: "LICENSE_ACKNOWLEDGEMENT_REQUIRED", details: { reason: "acknowledgement_required" },
    });
    const createNewVersion = vi.fn()
      .mockRejectedValueOnce(apiError)
      .mockResolvedValueOnce({ item_id: "item-owned-1", version_id: "v2", gate_run_id: "gate-2", status: "verifying" } satisfies NewVersionResult);
    const { onSaved } = renderEditContent(makeItem(), createNewVersion);

    fireEvent.change(screen.getByTestId("edit-content-license"), { target: { value: "GPL-3.0-only" } });
    fireEvent.click(screen.getByTestId("edit-content-save"));

    await waitFor(() => expect(screen.getByTestId("edit-content-license-ack-prompt")).toBeInTheDocument());
    expect(screen.getByTestId("edit-content-save")).toBeDisabled();

    fireEvent.click(screen.getByTestId("edit-content-license-acknowledge"));
    expect(screen.getByTestId("edit-content-save")).not.toBeDisabled();
    fireEvent.click(screen.getByTestId("edit-content-save"));

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(createNewVersion).toHaveBeenLastCalledWith(
      "item-owned-1", expect.anything(), "GPL-3.0-only", { licenseAcknowledged: true },
    );
  });

  it("shows the org-policy-blocked reason for an already-shared item, distinct from the acknowledgement prompt", async () => {
    const apiError = Object.assign(new Error("blocked by org policy"), { code: "LICENSE_NOT_ALLOWED_BY_ORG_POLICY" });
    const createNewVersion = vi.fn().mockRejectedValueOnce(apiError);
    renderEditContent(makeItem(), createNewVersion);

    fireEvent.change(screen.getByTestId("edit-content-license"), { target: { value: "GPL-3.0-only" } });
    fireEvent.click(screen.getByTestId("edit-content-save"));

    expect(await screen.findByTestId("edit-content-org-policy-blocked")).toBeInTheDocument();
    expect(screen.queryByTestId("edit-content-license-ack-prompt")).not.toBeInTheDocument();
  });

  it("Save picks up an edited license", async () => {
    const createNewVersion = vi.fn().mockResolvedValue({ item_id: "item-owned-1", version_id: "v2", gate_run_id: "gate-2", status: "verifying" } satisfies NewVersionResult);
    renderEditContent(makeItem(), createNewVersion);

    fireEvent.change(screen.getByTestId("edit-content-license"), { target: { value: "Apache-2.0" } });
    fireEvent.click(screen.getByTestId("edit-content-save"));

    await waitFor(() => expect(createNewVersion).toHaveBeenCalledTimes(1));
    expect(createNewVersion.mock.calls[0]?.[2]).toBe("Apache-2.0");
  });

  it("Save is disabled when SKILL.md's own instructions are empty", () => {
    renderEditContent(makeItem({ manifest: { instructions: "", files: {} } }), vi.fn());
    expect(screen.getByTestId("edit-content-save")).toBeDisabled();
  });

  it("adding a file includes it in the next Save's payload", async () => {
    const createNewVersion = vi.fn().mockResolvedValue({ item_id: "item-owned-1", version_id: "v2", gate_run_id: "gate-2", status: "verifying" } satisfies NewVersionResult);
    renderEditContent(makeItem(), createNewVersion);

    fireEvent.click(screen.getByTestId("edit-content-add-file"));
    fireEvent.change(screen.getByTestId("edit-content-new-file-name"), { target: { value: "scripts/run.py" } });
    fireEvent.click(screen.getByTestId("edit-content-new-file-confirm"));

    expect(screen.getByTestId("edit-content-file-scripts/run.py")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("edit-content-save"));
    await waitFor(() => expect(createNewVersion).toHaveBeenCalledTimes(1));
    const files = createNewVersion.mock.calls[0]?.[1].files as Array<{ name: string; content: string }>;
    expect(files.map((f) => f.name)).toContain("scripts/run.py");
  });

  it("rejects a path-traversal file name", () => {
    renderEditContent(makeItem(), vi.fn());
    fireEvent.click(screen.getByTestId("edit-content-add-file"));
    fireEvent.change(screen.getByTestId("edit-content-new-file-name"), { target: { value: "../../etc/passwd" } });
    fireEvent.click(screen.getByTestId("edit-content-new-file-confirm"));
    expect(screen.queryByTestId('edit-content-file-../../etc/passwd')).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("rejects a duplicate file name", () => {
    renderEditContent(makeItem(), vi.fn());
    fireEvent.click(screen.getByTestId("edit-content-add-file"));
    fireEvent.change(screen.getByTestId("edit-content-new-file-name"), { target: { value: "references/notes.md" } });
    fireEvent.click(screen.getByTestId("edit-content-new-file-confirm"));
    expect(screen.getByText(/already exists/)).toBeInTheDocument();
  });

  it("renaming a file updates the tree and the next Save's payload", async () => {
    const createNewVersion = vi.fn().mockResolvedValue({ item_id: "item-owned-1", version_id: "v2", gate_run_id: "gate-2", status: "verifying" } satisfies NewVersionResult);
    renderEditContent(makeItem(), createNewVersion);

    fireEvent.click(screen.getByTestId("edit-content-rename-1"));
    fireEvent.change(screen.getByTestId("edit-content-rename-input-1"), { target: { value: "references/renamed.md" } });
    fireEvent.click(screen.getByTestId("edit-content-rename-confirm-1"));

    expect(screen.getByTestId("edit-content-file-references/renamed.md")).toBeInTheDocument();
    expect(screen.queryByTestId("edit-content-file-references/notes.md")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("edit-content-save"));
    await waitFor(() => expect(createNewVersion).toHaveBeenCalledTimes(1));
    const files = createNewVersion.mock.calls[0]?.[1].files as Array<{ name: string; content: string }>;
    expect(files.map((f) => f.name)).toEqual(["references/renamed.md"]);
  });

  it("deleting a file removes it from the tree and the next Save's payload", async () => {
    const createNewVersion = vi.fn().mockResolvedValue({ item_id: "item-owned-1", version_id: "v2", gate_run_id: "gate-2", status: "verifying" } satisfies NewVersionResult);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderEditContent(makeItem(), createNewVersion);

    fireEvent.click(screen.getByTestId("edit-content-delete-1"));
    expect(screen.queryByTestId("edit-content-file-references/notes.md")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("edit-content-save"));
    await waitFor(() => expect(createNewVersion).toHaveBeenCalledTimes(1));
    expect(createNewVersion.mock.calls[0]?.[1].files).toEqual([]);
    vi.restoreAllMocks();
  });

  it("shows a save error and does not call onSaved when the backend rejects it", async () => {
    const createNewVersion = vi.fn().mockRejectedValue(new Error("license not allowed"));
    const { onSaved } = renderEditContent(makeItem(), createNewVersion);

    fireEvent.click(screen.getByTestId("edit-content-save"));

    expect(await screen.findByRole("alert")).toHaveTextContent("license not allowed");
    expect(onSaved).not.toHaveBeenCalled();
  });
});

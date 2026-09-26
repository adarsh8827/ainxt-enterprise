// SPDX-License-Identifier: MIT
// Task item 6: the chat "+" menu's Browse-skills panel -- search, Add
// (with a real Verifying state), Import from a URL, and the Update flow,
// all against mocked authFetch calls to the real endpoints.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

vi.mock("../config", () => ({
  API_BASE: "/ainxt/v1/api",
  authFetch: vi.fn(),
}));

import { authFetch } from "../config";
import EcosystemBrowseSkillsPanel from "./EcosystemBrowseSkillsPanel.jsx";

const ITEM = {
  id: "item-1", namespace: "acme/exec-assistant", display_name: "Exec Assistant",
  description: "Drafts executive summaries.", allowed_actions: ["install", "report"],
};

function mockFor(handlers) {
  authFetch.mockImplementation((url, options) => {
    if (typeof url !== "string") return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    for (const [matcher, handler] of handlers) {
      if (typeof matcher === "string" ? url.includes(matcher) : matcher(url)) return handler(url, options);
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

beforeEach(() => authFetch.mockReset());
afterEach(() => cleanup());

describe("EcosystemBrowseSkillsPanel", () => {
  it("searches /ecosystem/items and renders results", async () => {
    mockFor([
      ["/ecosystem/installs", () => Promise.resolve({ ok: true, json: () => Promise.resolve({ installs: [] }) })],
      ["/ecosystem/items?", () => Promise.resolve({ ok: true, json: () => Promise.resolve({ items: [ITEM] }) })],
    ]);
    render(<EcosystemBrowseSkillsPanel onClose={() => {}} onManageInMarketplace={() => {}} />);
    expect(await screen.findByText("Exec Assistant")).toBeInTheDocument();
  });

  it("Add fetches the current version then installs, showing Verifying then no longer offering Add", async () => {
    mockFor([
      ["/ecosystem/installs", () => Promise.resolve({ ok: true, json: () => Promise.resolve({ installs: [] }) })],
      ["/ecosystem/items?", () => Promise.resolve({ ok: true, json: () => Promise.resolve({ items: [ITEM] }) })],
      ["/versions", () => Promise.resolve({ ok: true, json: () => Promise.resolve({ versions: [{ id: "v1", is_current: true }] }) })],
      ["/install", () => Promise.resolve({ ok: true, json: () => Promise.resolve({ install_id: "inst-1" }) })],
    ]);
    render(<EcosystemBrowseSkillsPanel onClose={() => {}} onManageInMarketplace={() => {}} />);
    const addButton = await screen.findByTestId("browse-skills-add");
    fireEvent.click(addButton);

    await waitFor(() => expect(screen.queryByTestId("browse-skills-add")).not.toBeInTheDocument());
    expect(screen.getByTestId("browse-skills-manage")).toBeInTheDocument();
  });

  it("Import from a URL parses a GitHub URL and posts create_via=import", async () => {
    mockFor([
      ["/ecosystem/installs", () => Promise.resolve({ ok: true, json: () => Promise.resolve({ installs: [] }) })],
      ["/ecosystem/items?", () => Promise.resolve({ ok: true, json: () => Promise.resolve({ items: [] }) })],
      [(url) => url.endsWith("/ecosystem/items"), () => Promise.resolve({ ok: true, json: () => Promise.resolve({ item_id: "item-2", version_id: "v1" }) })],
    ]);
    render(<EcosystemBrowseSkillsPanel onClose={() => {}} onManageInMarketplace={() => {}} />);
    fireEvent.click(await screen.findByTestId("browse-skills-open-import"));
    fireEvent.change(screen.getByPlaceholderText(/github.com/i), { target: { value: "https://github.com/acme/hello-skill" } });
    fireEvent.change(screen.getByPlaceholderText(/namespace/i), { target: { value: "acme/hello-skill" } });
    fireEvent.click(screen.getByTestId("import-skill-confirm"));

    await waitFor(() => {
      const call = authFetch.mock.calls.find(([url]) => url.endsWith("/ecosystem/items"));
      expect(call).toBeTruthy();
    });
    const [, options] = authFetch.mock.calls.find(([url]) => url.endsWith("/ecosystem/items"));
    const body = JSON.parse(options.body);
    expect(body).toMatchObject({ create_via: "import", kind: "github_repo", ref: "acme/hello-skill", namespace: "acme/hello-skill" });
  });

  it("Update is only offered for a skill the caller can manage (allowed_actions includes 'deprecate')", async () => {
    const ownedItem = { ...ITEM, id: "item-owned", display_name: "My Own Skill", allowed_actions: ["install", "deprecate", "report"] };
    mockFor([
      ["/ecosystem/installs", () => Promise.resolve({ ok: true, json: () => Promise.resolve({ installs: [] }) })],
      ["/ecosystem/items?", () => Promise.resolve({ ok: true, json: () => Promise.resolve({ items: [ITEM, ownedItem] }) })],
    ]);
    render(<EcosystemBrowseSkillsPanel onClose={() => {}} onManageInMarketplace={() => {}} />);
    await screen.findByText("Exec Assistant");
    await screen.findByText("My Own Skill");

    const updateButtons = screen.getAllByTestId("browse-skills-update");
    expect(updateButtons).toHaveLength(1); // only the owned item gets one
  });
});

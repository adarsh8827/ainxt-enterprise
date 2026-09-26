// SPDX-License-Identifier: MIT
// Task F-11: chat-runtime slash menu + "+" menu Ecosystem skills. Flag read
// inside a function (not a module-level const) so vi.stubEnv() actually
// takes effect -- see the identical bug/fix already applied for
// AgentStudio/frontend's CatalogPicker.jsx (task B-24).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor, cleanup } from "@testing-library/react";

vi.mock("../config", () => ({
  API_BASE: "/ainxt/v1/api",
  authFetch: vi.fn(),
}));

import { authFetch } from "../config";
import { isEcosystemChatSkillsEnabled, useEcosystemChatSkills } from "./useEcosystemChatSkills";

afterEach(() => cleanup());

describe("isEcosystemChatSkillsEnabled", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("is false by default", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "false");
    expect(isEcosystemChatSkillsEnabled()).toBe(false);
  });

  it("is true only when explicitly set to the string 'true'", () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    expect(isEcosystemChatSkillsEnabled()).toBe(true);
  });
});

describe("useEcosystemChatSkills", () => {
  beforeEach(() => authFetch.mockReset());
  afterEach(() => vi.unstubAllEnvs());

  it("flag off: never calls the API and returns an empty, disabled result", async () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "false");
    const { result } = renderHook(() => useEcosystemChatSkills());
    expect(result.current).toEqual({ enabled: false, skills: [] });
    expect(authFetch).not.toHaveBeenCalled();
  });

  it("flag on: fetches GET /ecosystem/capabilities?surface=chat and returns its skills", async () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    const skills = [
      { namespace: "acme/exec-assistant", display_name: "Exec Assistant", description: "d", slash_command: "/exec-assistant" },
    ];
    authFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ skills }) });

    const { result } = renderHook(() => useEcosystemChatSkills());
    await waitFor(() => expect(result.current.skills).toEqual(skills));

    expect(result.current.enabled).toBe(true);
    expect(authFetch).toHaveBeenCalledWith("/ainxt/v1/api/ecosystem/capabilities?surface=chat");
  });

  it("flag on: a non-ok response resolves to an empty skills list, not a thrown error", async () => {
    vi.stubEnv("VITE_ECOSYSTEM_CHAT_SKILLS", "true");
    authFetch.mockResolvedValue({ ok: false, json: () => Promise.resolve({}) });

    const { result } = renderHook(() => useEcosystemChatSkills());
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(result.current.skills).toEqual([]);
    expect(result.current.enabled).toBe(true);
  });
});

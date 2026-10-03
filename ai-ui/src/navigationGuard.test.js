// SPDX-License-Identifier: MIT
import { afterEach, describe, expect, it, vi } from "vitest";
import { setNavigationGuard, clearNavigationGuard, confirmNavigationAllowed } from "./navigationGuard";

afterEach(() => clearNavigationGuard());

describe("navigationGuard", () => {
  it("allows navigation with no guard registered -- the default state for every page that never opts in", async () => {
    expect(await confirmNavigationAllowed()).toBe(true);
  });

  it("defers to a registered guard's own return value", async () => {
    setNavigationGuard(() => false);
    expect(await confirmNavigationAllowed()).toBe(false);
    setNavigationGuard(() => true);
    expect(await confirmNavigationAllowed()).toBe(true);
  });

  it("awaits an async guard (e.g. one showing its own confirm dialog) before deciding", async () => {
    let resolveGuard;
    setNavigationGuard(() => new Promise((resolve) => { resolveGuard = resolve; }));
    const pending = confirmNavigationAllowed();
    resolveGuard(false);
    expect(await pending).toBe(false);
  });

  it("clearNavigationGuard() removes it -- back to the default 'allow' once a page unmounts", async () => {
    setNavigationGuard(() => false);
    clearNavigationGuard();
    expect(await confirmNavigationAllowed()).toBe(true);
  });

  it("a guard that throws fails open -- a bug in one guard must never permanently trap the user on a page", async () => {
    setNavigationGuard(() => { throw new Error("boom"); });
    expect(await confirmNavigationAllowed()).toBe(true);
  });

  it("a newly registered guard replaces whatever was there before", async () => {
    const first = vi.fn(() => true);
    const second = vi.fn(() => false);
    setNavigationGuard(first);
    setNavigationGuard(second);
    expect(await confirmNavigationAllowed()).toBe(false);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});

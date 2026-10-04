// SPDX-License-Identifier: MIT
// BUG-U04 fix: detailPath()/parseRoute() now round-trip an optional
// "?tab=..." deep-link seed for Detail's initial tab (used by Yours'
// "Versions & rollback" menu item) -- this is a one-time seed only, never
// mutated by in-page tab switches (see routing.js's own comment).
import { describe, expect, it } from "vitest";
import { detailPath, parseRoute } from "@marketplace/lib/routing";
describe("routing", () => {
  it("detailPath with no initialTab omits the query string, unchanged from before", () => {
    expect(detailPath("skills", "acme/my-skill")).toBe("/skills/acme/my-skill");
  });
  it("detailPath with an initialTab appends '?tab=...'", () => {
    expect(detailPath("skills", "acme/my-skill", "versions")).toBe("/skills/acme/my-skill?tab=versions");
  });
  it("parseRoute reads the tab back out as initialTab", () => {
    const route = parseRoute("/skills/acme/my-skill?tab=versions");
    expect(route).toMatchObject({
      kind: "catalog",
      typeSlug: "skills",
      namespace: "acme/my-skill",
      initialTab: "versions"
    });
  });
  it("parseRoute with no query string reports initialTab as null", () => {
    const route = parseRoute("/skills/acme/my-skill");
    expect(route.initialTab).toBeNull();
  });
  it("a namespace containing '/' still parses correctly alongside a tab query string", () => {
    const route = parseRoute("/skills/acme/nested/my-skill?tab=contents");
    expect(route.namespace).toBe("acme/nested/my-skill");
    expect(route.initialTab).toBe("contents");
  });
});
